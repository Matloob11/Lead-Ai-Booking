<?php
/**
 * A7 Lead Report — page opened from the Worktime grid "Lead report" button (admins only).
 * Deployed to: /home/bitrix/www/bitrix/tools/a7_lead_report.php
 *
 * GET user_id=123 &mode=day|week|month|range &date= &month= &from= &to= (see A7TaskReport::period)
 *     &show=days|worked|notworked
 * Data rules: A7LeadReport (a7_lead_report.php) — only the agent's own work counts.
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');

foreach (['A7TaskReport' => 'a7_task_report.php', 'A7LeadReport' => 'a7_lead_report.php'] as $cls => $file) {
    $inc = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/' . $file;
    if (!class_exists($cls) && is_readable($inc)) {
        require_once $inc;
    }
}

function a7lr_fail(int $code, string $msg): void
{
    http_response_code($code);
    echo '<!doctype html><meta charset="utf-8"><body style="font:14px system-ui;padding:32px;color:#525c69">'
        . htmlspecialcharsbx($msg) . '</body>';
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7lr_fail(401, 'Please log in to Bitrix first.');
}
if (!class_exists('A7TaskReport') || !class_exists('A7LeadReport')) {
    a7lr_fail(500, 'Lead report is not installed.');
}
$viewerId = (int) $USER->GetID();
if (!A7LeadReport::isAdmin($viewerId)) {
    a7lr_fail(403, 'The lead report is for admins only.');
}
$userId = (int) ($_GET['user_id'] ?? 0);
if ($userId <= 0 || in_array($userId, A7LeadReport::EXCLUDE_USERS, true)) {
    a7lr_fail(400, 'No agent selected.');
}

$tz = new DateTimeZone(A7TaskReport::TZ);
$now = new DateTime('now', $tz);
$d = static fn(string $ymd) => new DateTime($ymd . ' 00:00:00', $tz);
$p = A7TaskReport::period($_GET);
['mode' => $mode, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to, 'title' => $title,
    'isCurrent' => $isCurrent, 'today' => $t, 'months' => $months] = $p;
$show = in_array($_GET['show'] ?? '', ['days', 'worked', 'notworked'], true) ? $_GET['show'] : 'days';

$data = A7LeadReport::build($userId, $from, $to);
$s = $data['summary'];
$userName = A7TaskReport::userName($userId);

$state = ['user_id' => $userId, 'mode' => $mode, 'show' => $show, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to];
$url = static fn(array $over = []) => A7TaskReport::periodQuery($state, $over);
$prev = $url($p['prev']);
$next = $url($p['next']);

$h = static fn($v) => htmlspecialcharsbx((string) $v);
$pct = static fn(int $a, int $b) => $b > 0 ? (int) round($a * 100 / $b) : 0;
$time = static fn(int $x) => (new DateTime('@' . $x))->setTimezone($tz)->format('d M, h:i A');
$fmtDay = static function (string $day) use ($t, $d): string {
    $yesterday = $d($t)->modify('-1 day')->format('Y-m-d');
    $prefix = $day === $t ? 'Today · ' : ($day === $yesterday ? 'Yesterday · ' : '');
    return $prefix . $d($day)->format('D, d M Y');
};
$modes = ['day' => 'Day', 'week' => 'Week', 'month' => 'Month', 'range' => 'Custom'];
$shows = ['days' => 'Day by day', 'worked' => 'Worked leads (' . $s['workedTotal'] . ')', 'notworked' => 'Not worked (' . $s['notWorked'] . ')'];
$leadLink = static fn(int $id) => '/crm/lead/details/' . $id . '/';
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lead report — <?= $h($userName) ?></title>
<style>
  :root {
    --bg: #f5f7f8; --card: #fff; --ink: #333; --muted: #828b95; --line: #e6e9ec;
    --accent: #2fc6f6; --accent-ink: #0b66c3; --ok: #5a9e00; --bad: #ff5752;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 "Open Sans", "Helvetica Neue", Arial, sans-serif; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 24px 20px 48px; }
  h1 { font-size: 24px; font-weight: 400; margin: 0 0 4px; }
  .sub { color: var(--muted); margin-bottom: 16px; }
  .filters { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 16px; display: grid; gap: 10px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .row > .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; width: 52px; }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 18px; overflow: hidden; flex-wrap: wrap; }
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
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 12px; }
  .stat { background: var(--card); border-radius: 8px; padding: 12px 14px; border: 1px solid var(--line); }
  .stat b { display: block; font-size: 26px; font-weight: 600; line-height: 1.2; }
  .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  .stat small { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
  .stat.ok b { color: var(--ok); } .stat.bad b { color: var(--bad); }
  .bar { height: 6px; background: #ffe0df; border-radius: 3px; overflow: hidden; margin-top: 8px; }
  .bar i { display: block; height: 100%; background: #7bd500; }
  .mini { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
  .mini span { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 4px 12px; font-size: 13px; }
  .mini b { font-weight: 600; }
  table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; font-size: 13px; }
  th, td { padding: 9px 10px; border-top: 1px solid var(--line); text-align: right; white-space: nowrap; }
  th { background: #f0f3f5; color: #535c69; font-weight: 600; font-size: 12px; border-top: 0; }
  th:first-child, td:first-child, td.l, th.l { text-align: left; }
  td.l { white-space: normal; }
  td.bad { color: var(--bad); font-weight: 600; } td.ok { color: var(--ok); font-weight: 600; }
  td a { color: var(--accent-ink); text-decoration: none; font-weight: 600; }
  td a:hover { text-decoration: underline; }
  .muted { color: var(--muted); font-size: 12px; }
  .scroll { overflow-x: auto; }
  .empty { background: var(--card); border: 1px dashed var(--line); border-radius: 8px; padding: 40px; text-align: center; color: var(--muted); }
  .note { color: var(--muted); font-size: 12px; margin-top: 14px; }
  @media (max-width: 640px) { .row > .lbl { width: 100%; } }
</style>
</head>
<body>
<div class="wrap">
  <h1><?= $h($userName) ?> — Lead report</h1>
  <div class="sub">Only this agent's own work is counted: calls, stage changes, comments, edits, WhatsApp and follow-ups · Pakistan time</div>

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
    <div class="stat"><b><?= (int) $s['received'] ?></b><span>Leads received</span>
      <small>distinct leads<?= $s['assignments'] > $s['received'] ? ' · assigned ' . (int) $s['assignments'] . ' times' : '' ?></small></div>
    <div class="stat ok"><b><?= (int) $s['workedReceived'] ?></b><span>Worked on</span>
      <small><?= $pct($s['workedReceived'], $s['received']) ?>% of received</small>
      <div class="bar"><i style="width:<?= $pct($s['workedReceived'], $s['received']) ?>%"></i></div></div>
    <div class="stat bad"><b><?= (int) $s['notWorked'] ?></b><span>Not worked</span>
      <small>received, no action by the agent</small></div>
    <div class="stat"><b><?= (int) $s['workedTotal'] ?></b><span>All leads worked</span>
      <small>incl. leads received earlier</small></div>
  </div>
  <div class="mini">
    <span>📞 Calls <b><?= (int) $s['call'] ?></b> <span class="muted">(<?= (int) $s['answered'] ?> answered)</span></span>
    <span>Stage changes <b><?= (int) $s['stage'] ?></b></span>
    <span>Comments <b><?= (int) $s['comment'] ?></b></span>
    <span>Edits <b><?= (int) $s['edit'] ?></b></span>
    <span>WhatsApp <b><?= (int) $s['whatsapp'] ?></b></span>
    <span>Follow-ups <b><?= (int) $s['followup'] ?></b></span>
  </div>

  <?php if ($show === 'days'): ?>
    <?php if (!$data['days']): ?>
      <div class="empty">No leads and no lead work in this period.</div>
    <?php else: ?>
      <div class="scroll"><table>
        <tr><th class="l">Day</th><th>Received</th><th>Worked leads</th><th>Not worked</th><th>Calls</th><th>Answered</th><th>Stage</th><th>Comments</th><th>Edits</th><th>WhatsApp</th><th>Follow-ups</th></tr>
        <?php foreach ($data['days'] as $day => $r): ?>
          <tr>
            <td class="l"><a href="<?= $h($url(['mode' => 'day', 'date' => $day, 'show' => 'worked'])) ?>"><?= $h($fmtDay($day)) ?></a></td>
            <td><?= (int) $r['received'] ?></td>
            <td class="ok"><?= (int) $r['worked'] ?></td>
            <td class="<?= $r['notWorked'] ? 'bad' : '' ?>"><?= (int) $r['notWorked'] ?></td>
            <td><?= (int) $r['call'] ?></td><td><?= (int) $r['answered'] ?></td><td><?= (int) $r['stage'] ?></td>
            <td><?= (int) $r['comment'] ?></td><td><?= (int) $r['edit'] ?></td><td><?= (int) $r['whatsapp'] ?></td><td><?= (int) $r['followup'] ?></td>
          </tr>
        <?php endforeach; ?>
      </table></div>
      <div class="note">"Worked leads" = distinct leads the agent acted on that day. "Not worked" = leads received that day with no action by the agent afterwards (within the selected period). Click a day to open it.</div>
    <?php endif; ?>

  <?php elseif ($show === 'worked'): ?>
    <?php if (!$data['worked']): ?>
      <div class="empty">The agent did not work on any lead in this period.</div>
    <?php else: ?>
      <div class="scroll"><table>
        <tr><th class="l">Lead</th><th class="l">Current stage</th><th>Calls</th><th>Stage</th><th>Comments</th><th>Edits</th><th>WhatsApp</th><th>Follow-ups</th><th class="l">Last action</th></tr>
        <?php foreach ($data['worked'] as $id => $r): $ld = $data['leads'][$id] ?? null; ?>
          <tr>
            <td class="l"><a href="<?= $h($leadLink($id)) ?>" data-lead-link><?= $h($ld['title'] ?? ('Lead #' . $id)) ?></a>
              <?php if ($ld && $ld['owner'] !== $userId): ?><div class="muted">now with <?= $h($ld['ownerName']) ?></div><?php endif; ?></td>
            <td class="l"><?= $h($ld['stage'] ?? '') ?></td>
            <td><?= (int) $r['call'] ?><?= $r['answered'] ? ' <span class="muted">(' . (int) $r['answered'] . ')</span>' : '' ?></td>
            <td><?= (int) $r['stage'] ?></td><td><?= (int) $r['comment'] ?></td><td><?= (int) $r['edit'] ?></td>
            <td><?= (int) $r['whatsapp'] ?></td><td><?= (int) $r['followup'] ?></td>
            <td class="l"><?= $h($time($r['last'])) ?></td>
          </tr>
        <?php endforeach; ?>
      </table></div>
    <?php endif; ?>

  <?php else: ?>
    <?php if (!$data['notWorked']): ?>
      <div class="empty">Every lead received in this period was worked on.</div>
    <?php else: ?>
      <div class="scroll"><table>
        <tr><th class="l">Lead</th><th class="l">Received</th><th class="l">Current stage</th><th class="l">Now with</th></tr>
        <?php foreach ($data['notWorked'] as $id => $x): $ld = $data['leads'][$id] ?? null; ?>
          <tr>
            <td class="l"><a href="<?= $h($leadLink($id)) ?>" data-lead-link><?= $h($ld['title'] ?? ('Lead #' . $id)) ?></a></td>
            <td class="l"><?= $h($time($x)) ?></td>
            <td class="l"><?= $h($ld['stage'] ?? '') ?></td>
            <td class="l"><?= $h($ld ? ($ld['owner'] === $userId ? 'this agent' : $ld['ownerName']) : '') ?></td>
          </tr>
        <?php endforeach; ?>
      </table></div>
    <?php endif; ?>
  <?php endif; ?>

  <?php if ($data['truncated']): ?>
    <div class="note">Lists show the latest <?= A7LeadReport::LIST_LIMIT ?> leads only — pick a shorter period to see the rest. The totals above are complete.</div>
  <?php endif; ?>
  <?php if (!$data['names']): ?>
    <div class="note">Could not match this user's name in the assignment history, so "Leads received" only counts new leads.</div>
  <?php endif; ?>
  <div class="note"><?= $isCurrent ? 'Updates on its own every 2 minutes while open. ' : '' ?>Last updated <?= $h($now->format('h:i A')) ?>.</div>
</div>
<script>
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-lead-link]');
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
  <?php if ($isCurrent): ?>
  setInterval(function () {
    if (document.visibilityState === 'visible') location.reload();
  }, 120000);
  <?php endif; ?>
</script>
</body>
</html>
