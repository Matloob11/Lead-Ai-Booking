<?php
/**
 * A7 Task Report — the page opened from the Worktime grid "Task report" button.
 * Deployed to: /home/bitrix/www/bitrix/tools/a7_task_report.php
 *
 * GET user_id=123
 *     &mode=day|week|month|range   (default month = this month)
 *     &date=Y-m-d                  (day: that day; week: the Mon–Sun week containing it)
 *     &month=Y-m                   (month)
 *     &from=Y-m-d&to=Y-m-d         (range, max 366 days)
 *     &show=all|completed|added|open
 * A task is listed on the day it was added and on the day it was completed (Pakistan time).
 * Access: A7TaskReport::canView (own report; admins + department heads: everyone).
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');

if (!class_exists('A7TaskReport')) {
    $inc = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_task_report.php';
    if (is_readable($inc)) {
        require_once $inc;
    }
}

function a7tr_fail(int $code, string $msg): void
{
    http_response_code($code);
    echo '<!doctype html><meta charset="utf-8"><body style="font:14px system-ui;padding:32px;color:#525c69">'
        . htmlspecialcharsbx($msg) . '</body>';
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7tr_fail(401, 'Please log in to Bitrix first.');
}
if (!class_exists('A7TaskReport')) {
    a7tr_fail(500, 'Task report is not installed.');
}

$viewerId = (int) $USER->GetID();
$userId = (int) ($_GET['user_id'] ?? 0);
if ($userId <= 0) {
    a7tr_fail(400, 'No user selected.');
}
if (!A7TaskReport::canView($viewerId, $userId)) {
    a7tr_fail(403, 'You do not have access to this user\'s report.');
}

/* ---------- period ---------- */
$tz = new DateTimeZone(A7TaskReport::TZ);
$now = new DateTime('now', $tz);
$d = static fn(string $ymd) => new DateTime($ymd . ' 00:00:00', $tz);
$p = A7TaskReport::period($_GET);
['mode' => $mode, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to, 'title' => $title,
    'isCurrent' => $isCurrent, 'today' => $t, 'months' => $months] = $p;
$show = in_array($_GET['show'] ?? '', ['all', 'completed', 'added', 'open'], true) ? $_GET['show'] : 'all';

$data = A7TaskReport::fetch($userId, $from, $to, $show);
$userName = A7TaskReport::userName($userId);
$s = $data['summary'];

/* ---------- links ---------- */
$state = ['user_id' => $userId, 'mode' => $mode, 'show' => $show, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to];
$url = static fn(array $over = []) => A7TaskReport::periodQuery($state, $over);
$prev = $url($p['prev']);
$next = $url($p['next']);

$h = static fn($v) => htmlspecialcharsbx((string) $v);
$fmtDay = static function (string $day) use ($t, $d): string {
    $yesterday = $d($t)->modify('-1 day')->format('Y-m-d');
    $prefix = $day === $t ? 'Today · ' : ($day === $yesterday ? 'Yesterday · ' : '');
    return $prefix . $d($day)->format('l, d F Y');
};
$modes = ['day' => 'Day', 'week' => 'Week', 'month' => 'Month', 'range' => 'Custom'];
$shows = ['all' => 'All', 'completed' => 'Completed', 'added' => 'Added', 'open' => 'Still open'];
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task report — <?= $h($userName) ?></title>
<style>
  :root {
    --bg: #f5f7f8; --card: #fff; --ink: #333; --muted: #828b95; --line: #e6e9ec;
    --accent: #2fc6f6; --accent-ink: #0b66c3;
    --done-bg: #f1fbd0; --prog-bg: #e5f9ff; --pend-bg: #fff4d6; --bad: #ff5752; --bad-bg: #ffe8e8; --grey-bg: #eef2f4;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 "Open Sans", "Helvetica Neue", Arial, sans-serif; }
  .wrap { max-width: 980px; margin: 0 auto; padding: 24px 20px 48px; }
  h1 { font-size: 24px; font-weight: 400; margin: 0 0 4px; }
  .sub { color: var(--muted); margin-bottom: 16px; }
  .filters { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 16px; display: grid; gap: 10px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .row > .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; width: 52px; }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 18px; overflow: hidden; }
  .seg a { padding: 6px 14px; text-decoration: none; color: var(--ink); font-size: 13px; border-left: 1px solid var(--line); }
  .seg a:first-child { border-left: 0; }
  .seg a:hover { background: #f0fbff; }
  .seg a.on { background: var(--accent); color: #fff; }
  form.pick { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); margin: 0; }
  form.pick input, form.pick select { border: 1px solid var(--line); border-radius: 4px; padding: 5px 6px; font: inherit; color: var(--ink); background: #fff; }
  form.pick button { border: 0; background: #3bc8f5; color: #fff; border-radius: 4px; padding: 6px 14px; font: inherit; cursor: pointer; }
  .nav { display: flex; align-items: center; gap: 10px; margin: 4px 0 16px; }
  .nav a { display: inline-flex; width: 30px; height: 30px; align-items: center; justify-content: center; border: 1px solid var(--line); border-radius: 50%; background: var(--card); color: var(--ink); text-decoration: none; font-size: 16px; }
  .nav a:hover { border-color: var(--accent); }
  .nav a.off { opacity: .35; pointer-events: none; }
  .nav b { font-size: 18px; font-weight: 400; }
  .nav .today { width: auto; border-radius: 15px; padding: 0 12px; font-size: 13px; margin-left: auto; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 22px; }
  .stat { background: var(--card); border-radius: 8px; padding: 12px 14px; border: 1px solid var(--line); }
  .stat b { display: block; font-size: 24px; font-weight: 600; }
  .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  .stat.ok b { color: #5a9e00; } .stat.bad b { color: var(--bad); }
  .day { margin-bottom: 18px; }
  .day-h { display: flex; justify-content: space-between; align-items: baseline; font-weight: 600; margin: 0 0 8px; }
  .day-h small { color: var(--muted); font-weight: 400; }
  .list { background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .task { display: grid; grid-template-columns: 64px 1fr auto; gap: 12px; padding: 11px 14px; border-top: 1px solid var(--line); align-items: start; }
  .task:first-child { border-top: 0; }
  .task.is-done { box-shadow: inset 3px 0 0 #7bd500; }
  .time { color: var(--muted); font-size: 12px; padding-top: 2px; }
  .title a { color: var(--accent-ink); text-decoration: none; font-weight: 600; }
  .title a:hover { text-decoration: underline; }
  .meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
  .meta .late { color: var(--bad); font-weight: 600; }
  .tags { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
  .tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; white-space: nowrap; background: var(--grey-bg); color: #535c69; }
  .ev-done { background: #7bd500; color: #fff; font-weight: 600; }
  .ev-added { background: #e5f9ff; color: #0b7fa6; }
  .s-done { background: var(--done-bg); color: #4b7a00; } .s-progress { background: var(--prog-bg); color: #0b7fa6; }
  .s-pending, .s-new, .s-control { background: var(--pend-bg); color: #9a6500; }
  .s-declined { background: var(--bad-bg); color: #c23b37; }
  .empty { background: var(--card); border: 1px dashed var(--line); border-radius: 8px; padding: 40px; text-align: center; color: var(--muted); }
  .note { color: var(--muted); font-size: 12px; margin-top: 16px; }
  @media (max-width: 640px) {
    .row > .lbl { width: 100%; }
    .task { grid-template-columns: 1fr; gap: 4px; }
    .tags { justify-content: flex-start; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1><?= $h($userName) ?> — Task report</h1>
  <div class="sub">Tasks created by or assigned to this user · listed on the day they were added and the day they were completed · Pakistan time</div>

  <div class="filters">
    <div class="row">
      <span class="lbl">Period</span>
      <span class="seg">
        <?php foreach ($modes as $k => $label): ?>
          <a class="<?= $mode === $k ? 'on' : '' ?>" href="<?= $h($url(['mode' => $k])) ?>"><?= $h($label) ?></a>
        <?php endforeach; ?>
      </span>
      <form class="pick" method="get">
        <input type="hidden" name="user_id" value="<?= $userId ?>">
        <input type="hidden" name="mode" value="<?= $h($mode) ?>">
        <input type="hidden" name="show" value="<?= $h($show) ?>">
        <?php if ($mode === 'day' || $mode === 'week'): ?>
          <?= $mode === 'week' ? 'Any day of the week' : 'Date' ?>
          <input type="date" name="date" value="<?= $h($date) ?>" max="<?= $h($t) ?>" onchange="this.form.submit()">
        <?php elseif ($mode === 'month'): ?>
          <select name="month" onchange="this.form.submit()">
            <?php foreach ($months as $k => $label): ?>
              <option value="<?= $h($k) ?>"<?= $k === $month ? ' selected' : '' ?>><?= $h($label) ?></option>
            <?php endforeach; ?>
          </select>
        <?php else: ?>
          From <input type="date" name="from" value="<?= $h($from) ?>" max="<?= $h($t) ?>">
          to <input type="date" name="to" value="<?= $h($to) ?>" max="<?= $h($t) ?>">
          <button type="submit">Show</button>
        <?php endif; ?>
      </form>
    </div>
    <div class="row">
      <span class="lbl">Show</span>
      <span class="seg">
        <?php foreach ($shows as $k => $label): ?>
          <a class="<?= $show === $k ? 'on' : '' ?>" href="<?= $h($url(['show' => $k])) ?>"><?= $h($label) ?></a>
        <?php endforeach; ?>
      </span>
    </div>
  </div>

  <div class="nav">
    <a href="<?= $h($prev) ?>" title="Previous">‹</a>
    <b><?= $h($title) ?></b>
    <a href="<?= $h($next) ?>" title="Next" class="<?= $isCurrent ? 'off' : '' ?>">›</a>
    <a class="today" href="<?= $h($url(['date' => $t, 'month' => $now->format('Y-m'), 'from' => $d($t)->modify('-6 days')->format('Y-m-d'), 'to' => $t])) ?>">Today</a>
  </div>

  <div class="stats">
    <div class="stat ok"><b><?= (int) $s['completed'] ?></b><span>Completed</span></div>
    <div class="stat"><b><?= (int) $s['added'] ?></b><span>Tasks added</span></div>
    <div class="stat"><b><?= (int) $s['open'] ?></b><span>Added, still open</span></div>
    <div class="stat bad"><b><?= (int) $s['overdue'] ?></b><span>Overdue</span></div>
  </div>

  <?php if (!$data['days']): ?>
    <div class="empty">No tasks for this <?= $h(strtolower($modes[$mode] === 'Custom' ? 'period' : $modes[$mode])) ?>.</div>
  <?php endif; ?>

  <?php foreach ($data['days'] as $day => $tasks):
      $doneCount = count(array_filter($tasks, static fn($x) => $x['completed'])); ?>
    <section class="day">
      <div class="day-h"><span><?= $h($fmtDay($day)) ?></span>
        <small><?= $doneCount ?> completed · <?= count($tasks) ?> task<?= count($tasks) === 1 ? '' : 's' ?></small></div>
      <div class="list">
        <?php foreach ($tasks as $tk): ?>
          <div class="task<?= $tk['completed'] ? ' is-done' : '' ?>">
            <div class="time"><?= $h($tk['time']) ?></div>
            <div>
              <div class="title"><a href="/company/personal/user/<?= $viewerId ?>/tasks/task/view/<?= (int) $tk['id'] ?>/" data-task-link><?= $h($tk['title']) ?></a></div>
              <div class="meta">
                <?php if ($tk['role'] === 'assigned'): ?>Assigned by <?= $h($tk['createdBy']) ?>
                <?php elseif ($tk['role'] === 'created'): ?>Assigned to <?= $h($tk['responsible']) ?>
                <?php else: ?>Own task<?php endif; ?>
                <?php if (!$tk['added'] && $tk['createdAt'] !== ''): ?> · Added <?= $h($tk['createdAt']) ?><?php endif; ?>
                <?php if ($tk['deadline'] !== ''): ?> · Deadline <span class="<?= $tk['overdue'] ? 'late' : '' ?>"><?= $h($tk['deadline']) ?><?= $tk['overdue'] ? ' (overdue)' : '' ?></span><?php endif; ?>
                <?php if (!$tk['completed'] && $tk['status'] === 5 && $tk['closedAt'] !== ''): ?> · Completed <?= $h($tk['closedAt']) ?><?php endif; ?>
              </div>
            </div>
            <div class="tags">
              <?php if ($tk['completed']): ?><span class="tag ev-done">✓ Completed</span><?php endif; ?>
              <?php if ($tk['added']): ?><span class="tag ev-added">+ Added</span><?php endif; ?>
              <?php if (!$tk['completed']): ?><span class="tag s-<?= $h($tk['statusCss']) ?>"><?= $h($tk['statusLabel']) ?></span><?php endif; ?>
            </div>
          </div>
        <?php endforeach; ?>
      </div>
    </section>
  <?php endforeach; ?>

  <?php if ($data['truncated']): ?>
    <div class="note">Showing the latest <?= A7TaskReport::MAX_ROWS ?> tasks only — pick a shorter period to see the rest.</div>
  <?php endif; ?>
  <div class="note"><?= $isCurrent ? 'Updates on its own every minute while open. ' : '' ?>Last updated <?= $h($now->format('h:i A')) ?>.</div>
</div>
<script>
  // Task links: open in the Bitrix side panel of the top window when available.
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-task-link]');
    if (!a) return;
    try {
      var top = window.top;
      if (top && top.BX && top.BX.SidePanel && top.BX.SidePanel.Instance) {
        e.preventDefault();
        top.BX.SidePanel.Instance.open(a.getAttribute('href'));
        return;
      }
    } catch (err) {}
    a.target = '_blank';
  });
  // Live: reload every 60 s while visible, when the period includes today (new / completed tasks show up).
  <?php if ($isCurrent): ?>
  setInterval(function () {
    if (document.visibilityState === 'visible') location.reload();
  }, 60000);
  <?php endif; ?>
</script>
</body>
</html>
