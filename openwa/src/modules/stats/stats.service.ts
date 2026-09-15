import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { ConfigService } from '@nestjs/config';
import { Repository } from 'typeorm';
import { Session, SessionStatus } from '../session/entities/session.entity';
import { Message, MessageDirection, MessageStatus } from '../message/entities/message.entity';
import { CacheService } from '../../common/cache';

/**
 * SQL for the time-series timestamp bucket, per DB dialect. SQLite has strftime(); Postgres has
 * neither strftime nor a case-insensitive bare `m.createdAt` (unquoted it folds to lowercase and
 * misses the quoted "createdAt" column) — so it needs to_char() with a quoted column. The hour
 * format yields an identical zero-padded, chronologically-sortable label on both engines, so the
 * GROUP BY/ORDER BY on the alias and the downstream map() are unchanged.
 */
export function timeSeriesTimestampSql(dbType: string, interval: 'hour' | 'day'): string {
  if (dbType === 'postgres') {
    const fmt = interval === 'hour' ? 'YYYY-MM-DD HH24:00:00' : 'YYYY-MM-DD';
    return `to_char(m."createdAt", '${fmt}')`;
  }
  const fmt = interval === 'hour' ? '%Y-%m-%d %H:00:00' : '%Y-%m-%d';
  return `strftime('${fmt}', m.createdAt)`;
}

/** SQL for the integer hour-of-day (0-23) bucket, per DB dialect. */
export function hourBucketSql(dbType: string): string {
  return dbType === 'postgres'
    ? `CAST(EXTRACT(HOUR FROM m."createdAt") AS INTEGER)`
    : `CAST(strftime('%H', m.createdAt) AS INTEGER)`;
}

/**
 * SQL for the most-recent-activity timestamp (MAX of createdAt) as an identical text format on both
 * engines. SQLite's MAX over a `datetime` column returns the stored text; Postgres returns a timestamp
 * the driver hydrates to a JS Date (serialized to a different ISO string). to_char/strftime pin both
 * to `YYYY-MM-DD HH:MM:SS`, matching the format the time-series buckets already use, so the lastActive
 * field is stable regardless of the backing database.
 */
export function maxCreatedAtSql(dbType: string): string {
  return dbType === 'postgres'
    ? `to_char(MAX(m."createdAt"), 'YYYY-MM-DD HH24:MI:SS')`
    : `strftime('%Y-%m-%d %H:%M:%S', MAX(m.createdAt))`;
}

export interface OverviewStats {
  sessions: {
    active: number;
    total: number;
    byStatus: Record<string, number>;
  };
  messages: {
    sent: number;
    received: number;
    failed: number;
    today: { sent: number; received: number };
  };
}

export interface TimeSeriesPoint {
  timestamp: string;
  sent: number;
  received: number;
}

export type StatsPeriod = '24h' | '7d' | '30d' | '1y';

/** First-reply median bands — same pace as Official Reports (agent performance). */
const PERF_MIN_SAMPLES = 3;
const PERF_BANDS: Array<{ key: string; label: string; ceiling: number | null }> = [
  { key: 'excellent', label: 'Excellent', ceiling: 5 * 60 },
  { key: 'good', label: 'Good', ceiling: 15 * 60 },
  { key: 'fair', label: 'Fair', ceiling: 60 * 60 },
  { key: 'bad', label: 'Bad', ceiling: 4 * 60 * 60 },
  { key: 'critical', label: 'Critical', ceiling: null },
];

export interface ResponseSpread {
  count: number;
  avgSeconds: number | null;
  medianSeconds: number | null;
  p90Seconds: number | null;
  slowestSeconds: number | null;
}

export interface ResponsePerformanceRow {
  sessionId: string;
  name: string;
  phone: string | null;
  sent: number;
  received: number;
  firstResponse: ResponseSpread;
  performance: { key: string; label: string };
}

export interface ResponsePerformance {
  bands: Array<{ key: string; label: string; detail: string }>;
  phones: ResponsePerformanceRow[];
  worst: ResponsePerformanceRow[];
  best: ResponsePerformanceRow[];
}

export interface MessageStats {
  timeSeries: TimeSeriesPoint[];
  byType: Record<string, number>;
  bySession: Array<{ sessionId: string; name: string; sent: number; received: number }>;
  topChats: Array<{ chatId: string; chatName: string | null; messageCount: number }>;
  /** Per linked phone — OpenWA has no Bitrix agent id on messages; session ≈ agent desk. */
  responsePerformance: ResponsePerformance;
}

export interface SessionStats {
  session: { id: string; name: string; status: string };
  messages: { sent: number; received: number; today: number; failed: number };
  topChats: Array<{ chatId: string; chatName: string | null; count: number; lastActive: string }>;
  hourlyActivity: Array<{ hour: number; sent: number; received: number }>;
}

@Injectable()
export class StatsService {
  /**
   * In-process TTL memo for the aggregate responses, keyed by query shape ('overview',
   * 'messages:<period>', 'session:<id>'). The aggregates run GROUP BY scans over the whole
   * messages table — on the default SQLite backend synchronously on the event loop — so
   * dashboard polling would otherwise re-run them on every request. TTL-only invalidation:
   * entries expire after stats.cacheTtlMs; there is no write-path hook. Session-scoped entries
   * are additionally re-validated on serve (getSessionStats), so a deleted session is not
   * resurrected from the memo. Key cardinality is
   * bounded (5 message periods + overview + one per session), so no size eviction is needed.
   */
  private readonly memo = new Map<string, { expiresAt: number; value: unknown }>();

  constructor(
    @InjectRepository(Session, 'data')
    private readonly sessionRepo: Repository<Session>,
    @InjectRepository(Message, 'data')
    private readonly messageRepo: Repository<Message>,
    private readonly cacheService: CacheService,
    private readonly configService: ConfigService,
  ) {}

  /** The data-connection dialect ('sqlite' | 'postgres'), used to pick portable date SQL. */
  private get dataDbType(): string {
    return this.messageRepo.manager.dataSource.options.type;
  }

  /** Memo TTL in ms; 0 disables memoization (every request hits the DB). Read per call. */
  private get memoTtlMs(): number {
    return this.configService.get<number>('stats.cacheTtlMs', 30000);
  }

  /** Returns the memoized value for `key` while fresh; otherwise computes, stores, returns it. */
  private async memoized<T>(key: string, compute: () => Promise<T>): Promise<T> {
    const ttl = this.memoTtlMs;
    if (ttl <= 0) return compute();
    const now = Date.now();
    const hit = this.memo.get(key);
    if (hit && hit.expiresAt > now) return hit.value as T;
    const value = await compute();
    this.memo.set(key, { expiresAt: now + ttl, value });
    return value;
  }

  async getOverview(): Promise<OverviewStats> {
    return this.memoized('overview', () => this.loadOverview());
  }

  private async loadOverview(): Promise<OverviewStats> {
    // Get session stats
    const sessions = await this.sessionRepo.find();
    const byStatus: Record<string, number> = {};
    let active = 0;

    for (const session of sessions) {
      byStatus[session.status] = (byStatus[session.status] || 0) + 1;
      if (session.status === SessionStatus.READY) active++;
    }

    // Get message stats
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);

    const messageStats = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.direction', 'direction')
      .addSelect('COUNT(*)', 'count')
      .groupBy('m.direction')
      .getRawMany<{ direction: string; count: string }>();

    const todayStats = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.direction', 'direction')
      .addSelect('COUNT(*)', 'count')
      .where('m.createdAt >= :todayStart', { todayStart })
      .groupBy('m.direction')
      .getRawMany<{ direction: string; count: string }>();

    const sent = parseInt(messageStats.find(m => m.direction === 'outgoing')?.count || '0');
    const received = parseInt(messageStats.find(m => m.direction === 'incoming')?.count || '0');
    const todaySent = parseInt(todayStats.find(m => m.direction === 'outgoing')?.count || '0');
    const todayReceived = parseInt(todayStats.find(m => m.direction === 'incoming')?.count || '0');

    // Count failed messages
    const failed = await this.messageRepo.count({
      where: { status: MessageStatus.FAILED },
    });

    // Cache session stats
    await this.cacheService.setSessionsStats({
      active,
      total: sessions.length,
      byStatus,
    });

    return {
      sessions: {
        active,
        total: sessions.length,
        byStatus,
      },
      messages: {
        sent,
        received,
        failed,
        today: { sent: todaySent, received: todayReceived },
      },
    };
  }

  async getMessageStats(period: StatsPeriod): Promise<MessageStats> {
    return this.memoized(`messages:${period}`, () => this.loadMessageStats(period));
  }

  private async loadMessageStats(period: StatsPeriod): Promise<MessageStats> {
    const since = this.getPeriodStart(period);
    const interval = period === '24h' ? 'hour' : 'day';

    // Time series - using raw query for SQLite compatibility
    const timeSeries = await this.getTimeSeries(since, interval);

    // By type. Rows with no body AND no metadata are content-less system/event rows (e.g. @lid
    // privacy-user events the engine maps to `unknown`) — counting them would put a misleading
    // "unknown" slice in the by-type chart, so they're excluded from the aggregation.
    const byTypeRaw = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.type', 'type')
      .addSelect('COUNT(*)', 'count')
      .where('m.createdAt >= :since', { since })
      .andWhere("(m.body IS NOT NULL AND m.body != '') OR m.metadata IS NOT NULL")
      .groupBy('m.type')
      .getRawMany<{ type: string; count: string }>();

    const byType: Record<string, number> = {};
    for (const row of byTypeRaw) {
      byType[row.type || 'unknown'] = parseInt(row.count);
    }

    // By session
    const bySessionRaw = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.sessionId', 'sessionId')
      .addSelect('m.direction', 'direction')
      .addSelect('COUNT(*)', 'count')
      .where('m.createdAt >= :since', { since })
      .groupBy('m.sessionId')
      .addGroupBy('m.direction')
      .getRawMany<{ sessionId: string; direction: string; count: string }>();

    const sessionMap = new Map<string, { sent: number; received: number }>();
    for (const row of bySessionRaw) {
      if (!sessionMap.has(row.sessionId)) {
        sessionMap.set(row.sessionId, { sent: 0, received: 0 });
      }
      const entry = sessionMap.get(row.sessionId)!;
      if (row.direction === 'outgoing') entry.sent = parseInt(row.count);
      else entry.received = parseInt(row.count);
    }

    const sessions = await this.sessionRepo.find();
    const sessionNames = new Map(sessions.map(s => [s.id, s.name]));

    const bySession = Array.from(sessionMap.entries()).map(([sessionId, stats]) => ({
      sessionId,
      name: sessionNames.get(sessionId) || 'Unknown',
      ...stats,
    }));

    // Top chats
    const topChats = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.chatId', 'chatId')
      .addSelect('COUNT(*)', 'messageCount')
      .addSelect('MAX(m.chatName)', 'chatName')
      .where('m.createdAt >= :since', { since })
      .groupBy('m.chatId')
      // Order by the aggregate expression, not the "messageCount" alias: Postgres folds an unquoted
      // ORDER BY messageCount to lowercase and 42703s against the quoted alias (SQLite tolerated it).
      .orderBy('COUNT(*)', 'DESC')
      .limit(10)
      .getRawMany<{ chatId: string; messageCount: string; chatName: string | null }>();

    const responsePerformance = await this.loadResponsePerformance(since, sessions, sessionMap);

    return {
      timeSeries,
      byType,
      bySession,
      topChats: topChats.map(c => ({
        chatId: c.chatId,
        chatName: c.chatName ?? null,
        messageCount: parseInt(c.messageCount),
      })),
      responsePerformance,
    };
  }

  async getSessionStats(sessionId: string): Promise<SessionStats> {
    // The memo has no write-path hook, so a `session:<id>` entry can outlive its session row and
    // would keep serving a deleted session's stats until the TTL expires. Re-check existence on
    // every call — a cheap primary-key lookup next to the aggregate scans the memo exists to
    // avoid — and drop the stale entry instead of serving it.
    const key = `session:${sessionId}`;
    if ((await this.sessionRepo.count({ where: { id: sessionId } })) === 0) {
      this.memo.delete(key);
      throw new NotFoundException('Session not found');
    }
    return this.memoized(key, () => this.loadSessionStats(sessionId));
  }

  private async loadSessionStats(sessionId: string): Promise<SessionStats> {
    const session = await this.sessionRepo.findOne({ where: { id: sessionId } });
    if (!session) {
      throw new NotFoundException('Session not found');
    }

    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);

    // Message counts
    const stats = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.direction', 'direction')
      .addSelect('COUNT(*)', 'count')
      .where('m.sessionId = :sessionId', { sessionId })
      .groupBy('m.direction')
      .getRawMany<{ direction: string; count: string }>();

    const todayCount = await this.messageRepo
      .createQueryBuilder('m')
      .where('m.sessionId = :sessionId', { sessionId })
      .andWhere('m.createdAt >= :todayStart', { todayStart })
      .getCount();

    const sent = parseInt(stats.find(s => s.direction === 'outgoing')?.count || '0');
    const received = parseInt(stats.find(s => s.direction === 'incoming')?.count || '0');

    // Count failed messages for this session
    const failed = await this.messageRepo.count({
      where: { sessionId, status: MessageStatus.FAILED },
    });

    // Top chats for this session
    const topChats = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.chatId', 'chatId')
      .addSelect('COUNT(*)', 'count')
      .addSelect(maxCreatedAtSql(this.dataDbType), 'lastActive')
      .addSelect('MAX(m.chatName)', 'chatName')
      .where('m.sessionId = :sessionId', { sessionId })
      .groupBy('m.chatId')
      .orderBy('count', 'DESC')
      .limit(10)
      .getRawMany<{ chatId: string; count: string; lastActive: string; chatName: string | null }>();

    // Hourly activity (last 24h)
    const hourlyActivity = await this.getHourlyActivity(sessionId);

    return {
      session: { id: session.id, name: session.name, status: session.status },
      messages: { sent, received, today: todayCount, failed },
      topChats: topChats.map(c => ({
        chatId: c.chatId,
        chatName: c.chatName ?? null,
        count: parseInt(c.count),
        lastActive: c.lastActive,
      })),
      hourlyActivity,
    };
  }

  private getPeriodStart(period: StatsPeriod): Date {
    const now = new Date();
    switch (period) {
      case '24h':
        return new Date(now.getTime() - 24 * 60 * 60 * 1000);
      case '7d':
        return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      case '30d':
        return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      case '1y':
        return new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
    }
  }

  private spread(gaps: number[]): ResponseSpread {
    if (!gaps.length) {
      return {
        count: 0,
        avgSeconds: null,
        medianSeconds: null,
        p90Seconds: null,
        slowestSeconds: null,
      };
    }
    const ordered = [...gaps].sort((a, b) => a - b);
    const mid = Math.floor(ordered.length / 2);
    const median =
      ordered.length % 2 === 0
        ? (ordered[mid - 1] + ordered[mid]) / 2
        : ordered[mid];
    const avg = ordered.reduce((a, b) => a + b, 0) / ordered.length;
    const p90 = ordered[Math.min(ordered.length - 1, Math.floor(ordered.length * 0.9))];
    return {
      count: ordered.length,
      avgSeconds: Math.round(avg),
      medianSeconds: Math.round(median),
      p90Seconds: Math.round(p90),
      slowestSeconds: Math.round(ordered[ordered.length - 1]),
    };
  }

  private performanceBand(spread: ResponseSpread): { key: string; label: string } {
    const median = spread.medianSeconds;
    if (spread.count < PERF_MIN_SAMPLES || median == null) {
      return { key: 'insufficient', label: 'Not enough data' };
    }
    for (const band of PERF_BANDS) {
      if (band.ceiling == null || median < band.ceiling) {
        return { key: band.key, label: band.label };
      }
    }
    return { key: 'critical', label: 'Critical' };
  }

  private performanceLegend() {
    return [
      { key: 'excellent', label: 'Excellent', detail: 'Median first reply under 5 minutes' },
      { key: 'good', label: 'Good', detail: 'Under 15 minutes' },
      { key: 'fair', label: 'Fair', detail: 'Under 1 hour' },
      { key: 'bad', label: 'Bad', detail: 'Under 4 hours' },
      { key: 'critical', label: 'Critical', detail: '4 hours or more' },
      {
        key: 'insufficient',
        label: 'Not enough data',
        detail: `Fewer than ${PERF_MIN_SAMPLES} timed replies in this period`,
      },
    ];
  }

  /**
   * First-reply gaps per linked phone (session). Customer inbound starts the
   * clock; the next outbound closes it. OpenWA messages have no Bitrix agent
   * id — session name is what the desk shows as the agent/phone label.
   */
  private async loadResponsePerformance(
    since: Date,
    sessions: Session[],
    sessionMap: Map<string, { sent: number; received: number }>,
  ): Promise<ResponsePerformance> {
    const rows = await this.messageRepo
      .createQueryBuilder('m')
      .select('m.sessionId', 'sessionId')
      .addSelect('m.chatId', 'chatId')
      .addSelect('m.direction', 'direction')
      .addSelect('m.createdAt', 'createdAt')
      .where('m.createdAt >= :since', { since })
      .orderBy('m.sessionId', 'ASC')
      .addOrderBy('m.chatId', 'ASC')
      .addOrderBy('m.createdAt', 'ASC')
      .getRawMany<{ sessionId: string; chatId: string; direction: string; createdAt: Date | string }>();

    const gapsBySession = new Map<string, number[]>();
    let curSession = '';
    let curChat = '';
    let waitingSince: Date | null = null;

    for (const row of rows) {
      const createdAt = row.createdAt instanceof Date ? row.createdAt : new Date(row.createdAt);
      if (row.sessionId !== curSession || row.chatId !== curChat) {
        curSession = row.sessionId;
        curChat = row.chatId;
        waitingSince = null;
      }
      if (row.direction === MessageDirection.INCOMING || row.direction === 'incoming') {
        if (waitingSince == null) waitingSince = createdAt;
      } else if (waitingSince != null) {
        const gap = (createdAt.getTime() - waitingSince.getTime()) / 1000;
        if (Number.isFinite(gap) && gap >= 0) {
          const list = gapsBySession.get(row.sessionId) || [];
          list.push(gap);
          gapsBySession.set(row.sessionId, list);
        }
        waitingSince = null;
      }
    }

    const phones: ResponsePerformanceRow[] = sessions.map(session => {
      const volume = sessionMap.get(session.id) || { sent: 0, received: 0 };
      const firstResponse = this.spread(gapsBySession.get(session.id) || []);
      return {
        sessionId: session.id,
        name: session.name || 'Unknown',
        phone: session.phone || null,
        sent: volume.sent,
        received: volume.received,
        firstResponse,
        performance: this.performanceBand(firstResponse),
      };
    });

    // Only phones with traffic in the window — empty desks clutter the ranks.
    const active = phones.filter(p => p.sent > 0 || p.received > 0 || p.firstResponse.count > 0);
    const ranked = active.filter(
      p => p.performance.key !== 'insufficient' && p.firstResponse.medianSeconds != null,
    );
    const worst = [...ranked]
      .sort(
        (a, b) =>
          (b.firstResponse.medianSeconds || 0) - (a.firstResponse.medianSeconds || 0) ||
          (b.firstResponse.count || 0) - (a.firstResponse.count || 0),
      )
      .slice(0, 10);
    const best = [...ranked]
      .sort(
        (a, b) =>
          (a.firstResponse.medianSeconds || 0) - (b.firstResponse.medianSeconds || 0) ||
          (b.firstResponse.count || 0) - (a.firstResponse.count || 0),
      )
      .slice(0, 10);

    return {
      bands: this.performanceLegend(),
      phones: active.sort((a, b) => b.sent + b.received - (a.sent + a.received)),
      worst,
      best,
    };
  }

  private async getTimeSeries(since: Date, interval: 'hour' | 'day'): Promise<TimeSeriesPoint[]> {
    // Alias the bucket as `bucket`, not `timestamp`: `timestamp` is a reserved type keyword in
    // PostgreSQL, so `GROUP BY timestamp` is not read as the output alias and the query 500s
    // ("column m.createdAt must appear in the GROUP BY"). SQLite tolerates it, hence the dialect-only
    // bug. The API field stays `timestamp` (mapped below).
    const raw = await this.messageRepo
      .createQueryBuilder('m')
      .select(timeSeriesTimestampSql(this.dataDbType, interval), 'bucket')
      .addSelect(`SUM(CASE WHEN m.direction = 'outgoing' THEN 1 ELSE 0 END)`, 'sent')
      .addSelect(`SUM(CASE WHEN m.direction = 'incoming' THEN 1 ELSE 0 END)`, 'received')
      .where('m.createdAt >= :since', { since })
      .groupBy('bucket')
      .orderBy('bucket', 'ASC')
      .getRawMany<{ bucket: string; sent: string; received: string }>();

    return raw.map(r => ({
      timestamp: r.bucket,
      sent: parseInt(r.sent || '0'),
      received: parseInt(r.received || '0'),
    }));
  }

  private async getHourlyActivity(sessionId: string): Promise<Array<{ hour: number; sent: number; received: number }>> {
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000);

    const raw = await this.messageRepo
      .createQueryBuilder('m')
      .select(hourBucketSql(this.dataDbType), 'hour')
      .addSelect(`SUM(CASE WHEN m.direction = 'outgoing' THEN 1 ELSE 0 END)`, 'sent')
      .addSelect(`SUM(CASE WHEN m.direction = 'incoming' THEN 1 ELSE 0 END)`, 'received')
      .where('m.sessionId = :sessionId', { sessionId })
      .andWhere('m.createdAt >= :since', { since })
      .groupBy('hour')
      .orderBy('hour', 'ASC')
      .getRawMany<{ hour: string; sent: string; received: string }>();

    // Fill in missing hours
    const result: Array<{ hour: number; sent: number; received: number }> = [];
    const hourMap = new Map(raw.map(r => [parseInt(r.hour), r]));

    for (let h = 0; h < 24; h++) {
      const data = hourMap.get(h);
      result.push({
        hour: h,
        sent: data ? parseInt(data.sent || '0') : 0,
        received: data ? parseInt(data.received || '0') : 0,
      });
    }

    return result;
  }
}
