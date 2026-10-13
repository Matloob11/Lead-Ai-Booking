<?php
/**
 * A7 Attendance report — all employees in one table, or one employee day by day (admins + HR viewers).
 * Deployed to: /home/bitrix/www/bitrix/tools/a7_attendance.php
 *
 * GET [user_id=123] &mode=day|week|month|range &date= &month= &from= &to=   (see A7TaskReport::period)
 * Rules: A7Attendance (a7_attendance.php), settings: a7_attendance.config.php.
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');

foreach (['A7TaskReport' => 'a7_task_report.php', 'A7LeadReport' => 'a7_lead_report.php', 'A7Attendance' => 'a7_attendance.php'] as $cls => $file) {
    $inc = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/' . $file;
    if (!class_exists($cls) && is_readable($inc)) {
        require_once $inc;
    }
}

function a7at_fail(int $code, string $msg): void
{
    http_response_code($code);
    echo '<!doctype html><meta charset="utf-8"><body style="font:14px system-ui;padding:32px;color:#525c69">'
        . htmlspecialcharsbx($msg) . '</body>';
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7at_fail(401, 'Please log in to Bitrix first.');
}
if (!class_exists('A7TaskReport') || !class_exists('A7LeadReport') || !class_exists('A7Attendance')) {
    a7at_fail(500, 'Attendance report is not installed.');
}
if (!A7Attendance::canView((int) $USER->GetID())) {
    a7at_fail(403, 'You do not have access to the attendance report.');
}

$tz = new DateTimeZone(A7TaskReport::TZ);
$now = new DateTime('now', $tz);
$d = static fn(string $ymd) => new DateTime($ymd . ' 00:00:00', $tz);
$p = A7TaskReport::period($_GET);
['mode' => $mode, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to, 'title' => $title,
    'isCurrent' => $isCurrent, 'today' => $t, 'months' => $months] = $p;
$one = max(0, (int) ($_GET['user_id'] ?? 0));
$cfg = A7Attendance::config();
$lateChoices = [15 => '15 min', 30 => '30 min', 60 => '1 hour'];
$late = (int) ($_GET['late'] ?? 0);
if (!isset($lateChoices[$late])) {
    $late = isset($lateChoices[(int) $cfg['grace_minutes']]) ? (int) $cfg['grace_minutes'] : 15;
}

$all = A7Attendance::build($from, $to, null, $late); // every listed employee (also feeds the picker)
$users = $all['users'];
$person = $one && isset($users[$one]) ? $users[$one] : null;

$state = ['user_id' => $one, 'mode' => $mode, 'show' => '', 'late' => $late, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to];
$url = static fn(array $over = []) => A7TaskReport::periodQuery($state, $over);
$prev = $url($p['prev']);
$next = $url($p['next']);

$h = static fn($v) => htmlspecialcharsbx((string) $v);
$clock = static fn(int $x) => $x > 0 ? (new DateTime('@' . $x))->setTimezone($tz)->format('h:i A') : '—';
$secClock = static fn(?int $s) => $s === null ? '—' : sprintf('%02d:%02d %s', ((intdiv($s, 3600) + 11) % 12) + 1, intdiv($s % 3600, 60), $s >= 43200 ? 'PM' : 'AM');
$hours = static fn(int $s) => $s > 0 ? sprintf('%dh %02dm', intdiv($s, 3600), intdiv($s % 3600, 60)) : '—';
$pct = static fn(int $a, int $b) => $b > 0 ? (int) round($a * 100 / $b) : 0;
$mins = static fn(int $m) => $m <= 0 ? '—' : ($m < 60 ? $m . ' min' : sprintf('%dh %02dm', intdiv($m, 60), $m % 60));
$modes = ['day' => 'Day', 'week' => 'Week', 'month' => 'Month', 'range' => 'Custom'];
$statusLabel = [
    'present' => ['Present', 'st-ok'], 'late' => ['Present · Late', 'st-late'], 'off' => ['Off (no clock-in)', 'st-bad'],
    'leave' => ['Leave', 'st-leave'], 'holiday' => ['Holiday', 'st-off'], 'weekend' => ['Sunday', 'st-off'],
    'offwork' => ['Worked on day off', 'st-ok'], 'upcoming' => ['—', 'st-off'], 'notjoined' => ['Not joined yet', 'st-off'],
];
$showLeave = false;
$totals = ['working' => 0, 'present' => 0, 'absent' => 0, 'late' => 0, 'leave' => 0, 'lateMin' => 0];
foreach ($users as $u) {
    foreach ($totals as $k => $_) {
        $totals[$k] += $u[$k];
    }
}
$showLeave = $totals['leave'] > 0;
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Attendance report<?= $person ? ' — ' . $h($person['name']) : '' ?></title>
<style>
  :root { --bg: #f5f7f8; --card: #fff; --ink: #333; --muted: #828b95; --line: #e6e9ec; --accent: #2fc6f6; --accent-ink: #0b66c3; --ok: #5a9e00; --bad: #e0413c; --late: #c77700; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 "Open Sans", "Helvetica Neue", Arial, sans-serif; }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px 48px; }
  h1 { font-size: 24px; font-weight: 400; margin: 0 0 4px; }
  .sub { color: var(--muted); margin-bottom: 16px; }
  .filters { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 16px; display: grid; gap: 10px; }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .row > .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; width: 70px; }
  .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 18px; overflow: hidden; }
  .seg a { padding: 6px 14px; text-decoration: none; color: var(--ink); font-size: 13px; border-left: 1px solid var(--line); }
  .seg a:first-child { border-left: 0; }
  .seg a:hover { background: #f0fbff; }
  .seg a.on { background: var(--accent); color: #fff; }
  form.pick { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); margin: 0; }
  input, select { border: 1px solid var(--line); border-radius: 4px; padding: 5px 8px; font: inherit; color: var(--ink); background: #fff; }
  button { border: 0; background: #3bc8f5; color: #fff; border-radius: 4px; padding: 6px 14px; font: inherit; cursor: pointer; }
  .nav { display: flex; align-items: center; gap: 10px; margin: 4px 0 16px; }
  .nav a { display: inline-flex; width: 30px; height: 30px; align-items: center; justify-content: center; border: 1px solid var(--line); border-radius: 50%; background: var(--card); color: var(--ink); text-decoration: none; font-size: 16px; }
  .nav a:hover { border-color: var(--accent); }
  .nav a.off { opacity: .35; pointer-events: none; }
  .nav b { font-size: 18px; font-weight: 400; }
  .nav .today { width: auto; border-radius: 15px; padding: 0 12px; font-size: 13px; margin-left: auto; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 16px; }
  .stat { background: var(--card); border-radius: 8px; padding: 12px 14px; border: 1px solid var(--line); }
  .stat b { display: block; font-size: 26px; font-weight: 600; line-height: 1.2; }
  .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
  .stat small { display: block; color: var(--muted); font-size: 12px; }
  .stat.ok b { color: var(--ok); } .stat.bad b { color: var(--bad); } .stat.late b { color: var(--late); }
  table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); font-size: 13px; }
  th, td { padding: 8px 10px; border-top: 1px solid var(--line); text-align: right; white-space: nowrap; }
  th { background: #f0f3f5; color: #535c69; font-weight: 600; font-size: 12px; border-top: 0; position: sticky; top: 0; cursor: pointer; user-select: none; }
  th.l, td.l { text-align: left; }
  td.l { white-space: normal; }
  td a { color: var(--accent-ink); text-decoration: none; font-weight: 600; }
  td a:hover { text-decoration: underline; }
  .num-bad { color: var(--bad); font-weight: 600; } .num-late { color: var(--late); font-weight: 600; } .num-ok { color: var(--ok); font-weight: 600; }
  .muted { color: var(--muted); font-size: 12px; }
  .tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 9px; background: #eef2f4; color: #535c69; margin-left: 4px; }
  .tag.auto { background: #fff4d6; color: #9a6500; }
  .st { display: inline-block; font-size: 12px; padding: 2px 9px; border-radius: 10px; }
  .st-ok { background: #f1fbd0; color: #4b7a00; } .st-late { background: #fff1d6; color: #9a5a00; }
  .st-bad { background: #ffe8e8; color: #c23b37; font-weight: 600; } .st-leave { background: #e5f9ff; color: #0b7fa6; }
  .st-off { background: #f3f4f6; color: #8a939c; }
  tr.dim td { color: #a0a7ae; }
  .scroll { overflow-x: auto; max-height: 70vh; overflow-y: auto; border-radius: 8px; }
  .note { color: var(--muted); font-size: 12px; margin-top: 14px; }
  .calc { background: #eef9fe; border: 1px solid #c9ecfb; color: #2b5d74; border-radius: 8px; padding: 9px 14px; font-size: 13px; margin-bottom: 16px; }
  .empty { background: var(--card); border: 1px dashed var(--line); border-radius: 8px; padding: 40px; text-align: center; color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
  <h1>Attendance report<?= $person ? ' — ' . $h($person['name']) : '' ?></h1>
  <div class="sub">From Bitrix clock-in / clock-out · Pakistan time ·
    <?php foreach ($cfg['offices'] as $o): ?><?= $h($o['name']) ?> <?= $h($o['start']) ?>–<?= $h($o['end']) ?><?php
      foreach ((array) ($o['history'] ?? []) as $hh): ?> (till <?= $h($d($hh['until'])->format('d M')) ?>: <?= $h($hh['start']) ?>–<?= $h($hh['end']) ?>)<?php endforeach; ?> · <?php endforeach; ?>
    late after <?= $h($lateChoices[$late]) ?> · Sunday off</div>

  <div class="filters">
    <div class="row">
      <span class="lbl">Period</span>
      <span class="seg">
        <?php foreach ($modes as $k => $label): ?>
          <a class="<?= $mode === $k ? 'on' : '' ?>" href="<?= $h($url(['mode' => $k])) ?>"><?= $h($label) ?></a>
        <?php endforeach; ?>
      </span>
      <form class="pick" method="get">
        <input type="hidden" name="user_id" value="<?= $one ?>">
        <input type="hidden" name="late" value="<?= $late ?>">
        <input type="hidden" name="mode" value="<?= $h($mode) ?>">
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
      <span class="lbl">Late after</span>
      <span class="seg">
        <?php foreach ($lateChoices as $k => $label): ?>
          <a class="<?= $late === $k ? 'on' : '' ?>" href="<?= $h($url(['late' => $k])) ?>"><?= $h($label) ?></a>
        <?php endforeach; ?>
      </span>
      <span class="muted">counted as late when the first clock-in is more than this after office start
        (<?php foreach ($cfg['offices'] as $o): ?><?= $h($o['name']) ?> <?= $h($o['start']) ?><?php foreach ((array) ($o['history'] ?? []) as $hh): ?>, till <?= $h($d($hh['until'])->format('d M')) ?> <?= $h($hh['start']) ?><?php endforeach; ?> · <?php endforeach; ?>)</span>
    </div>
    <div class="row">
      <span class="lbl">Employee</span>
      <form class="pick" method="get">
        <?php foreach (['mode' => $mode, 'late' => $late, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to] as $k => $v): ?>
          <input type="hidden" name="<?= $h($k) ?>" value="<?= $h($v) ?>">
        <?php endforeach; ?>
        <select name="user_id" onchange="this.form.submit()">
          <option value="0">All employees (<?= count($users) ?>)</option>
          <?php foreach ($users as $u): ?>
            <option value="<?= (int) $u['id'] ?>"<?= $u['id'] === $one ? ' selected' : '' ?>><?= $h($u['name']) ?></option>
          <?php endforeach; ?>
        </select>
      </form>
      <?php if (!$person): ?>
        <input type="search" id="q" placeholder="Search name…" autocomplete="off">
        <select id="office"><option value="">All offices</option>
          <?php foreach ($cfg['offices'] as $k => $o): ?><option value="<?= $h($k) ?>"><?= $h($o['name']) ?></option><?php endforeach; ?>
        </select>
      <?php endif; ?>
    </div>
  </div>

  <div class="nav">
    <a href="<?= $h($prev) ?>" title="Previous">‹</a>
    <b><?= $h($title) ?></b>
    <a href="<?= $h($next) ?>" title="Next" class="<?= $isCurrent ? 'off' : '' ?>">›</a>
    <a class="today" href="<?= $h($url(['date' => $t, 'month' => $now->format('Y-m'), 'from' => $d($t)->modify('-6 days')->format('Y-m-d'), 'to' => $t])) ?>">Today</a>
  </div>

  <div class="calc">
    <b><?= (int) $all['workingSoFar'] ?></b> working days so far<?= $all['workingSoFar'] !== $all['workingAll'] ? ' of <b>' . (int) $all['workingAll'] . '</b> in this period' : '' ?>
    · Monday–Saturday, Sunday off<?= $cfg['holidays'] ? ', holidays excluded' : '' ?>
    · late = more than <?= $h($lateChoices[$late]) ?> after office start
    · every clock-in day = Present, every working day without clock-in = Off
  </div>

  <?php if ($person): $u = $person; ?>
    <div class="stats">
      <div class="stat"><b><?= (int) $u['working'] ?></b><span>Working days so far</span><small><?= $h($u['officeName']) ?> <?= $h($u['officeHours']) ?><?= $u['joined'] ? ' · joined ' . $h($d($u['joined'])->format('d M')) : '' ?></small></div>
      <div class="stat ok"><b><?= (int) $u['present'] ?></b><span>Present</span><small><?= $pct($u['present'], $u['working']) ?>%</small></div>
      <div class="stat bad"><b><?= (int) $u['absent'] ?></b><span>Off</span><small>no clock-in</small></div>
      <div class="stat late"><b><?= (int) $u['late'] ?></b><span>Late arrivals</span><small>after <?= $h($lateChoices[$late]) ?></small></div>
      <div class="stat late"><b><?= $h($mins((int) $u['lateMin'])) ?></b><span>Total late time</span><small><?= $u['late'] ? 'avg ' . $h($mins((int) round($u['lateMin'] / $u['late']))) . ' per late day' : '' ?></small></div>
      <?php if ($u['leave']): ?><div class="stat"><b><?= (int) $u['leave'] ?></b><span>Leave</span><small>Absence chart</small></div><?php endif; ?>
      <div class="stat"><b><?= $h($hours($u['workedSec'])) ?></b><span>Total hours</span><small>avg in <?= $h($secClock($u['avgIn'])) ?></small></div>
    </div>
    <?php if ($u['auto']): ?><div class="note" style="margin:-6px 0 12px">⚠ Clock-in/out of this user is automatic (<?= $h($u['auto']) ?>).</div><?php endif; ?>
    <div class="scroll"><table>
      <tr><th class="l">Day</th><th class="l">Status</th><th>Office hours</th><th>Clock-in</th><th>Late by</th><th>Clock-out</th><th>Hours</th><th class="l">Note</th></tr>
      <?php foreach (array_reverse($u['days'], true) as $day => $x):
          [$lbl, $cls] = $statusLabel[$x['status']] ?? [$x['status'], 'st-off'];
          $dim = in_array($x['status'], ['weekend', 'upcoming', 'notjoined'], true); ?>
        <tr class="<?= $dim ? 'dim' : '' ?>">
          <td class="l"><?= $h($d($day)->format('D, d M')) ?></td>
          <td class="l"><span class="st <?= $cls ?>"><?= $h($lbl) ?></span></td>
          <td class="muted"><?= $dim ? '' : $h($x['hours']) ?></td>
          <td class="<?= $x['late'] ? 'num-late' : '' ?>"><?= $h($clock($x['in'])) ?></td>
          <td class="<?= $x['late'] ? 'num-late' : '' ?>"><?= $x['late'] ? $h($mins((int) $x['lateBy'])) : '' ?></td>
          <td><?= $x['noOut'] ? '<span class="num-bad">no clock-out</span>' : $h($clock($x['out'])) ?></td>
          <td><?= $h($hours($x['worked'])) ?></td>
          <td class="l muted"><?= $h($x['note']) ?></td>
        </tr>
      <?php endforeach; ?>
    </table></div>

  <?php elseif (!$users): ?>
    <div class="empty">No clock-ins in this period.</div>
  <?php else: ?>
    <div class="stats">
      <div class="stat"><b><?= count($users) ?></b><span>Employees</span></div>
      <div class="stat ok"><b><?= $pct($totals['present'], $totals['working']) ?>%</b><span>Attendance</span><small><?= (int) $totals['present'] ?> of <?= (int) $totals['working'] ?> working days</small></div>
      <div class="stat bad"><b><?= (int) $totals['absent'] ?></b><span>Off days</span><small>no clock-in</small></div>
      <div class="stat late"><b><?= (int) $totals['late'] ?></b><span>Late arrivals</span><small>after <?= $h($lateChoices[$late]) ?></small></div>
      <div class="stat late"><b><?= $h($mins((int) $totals['lateMin'])) ?></b><span>Total late time</span></div>
      <?php if ($totals['leave']): ?><div class="stat"><b><?= (int) $totals['leave'] ?></b><span>Leave days</span></div><?php endif; ?>
    </div>
    <div class="scroll"><table id="grid">
      <thead><tr>
        <th class="l" data-k="name">Employee</th><th class="l" data-k="office">Office</th>
        <th data-k="working">Working days</th><th data-k="present">Present</th><th data-k="absent">Off</th>
        <th data-k="late">Late</th><th data-k="latemin">Late time</th><?php if ($showLeave): ?><th data-k="leave">Leave</th><?php endif; ?>
        <th data-k="noout">No clock-out</th><th data-k="avgin">Avg clock-in</th><th data-k="hours">Total hours</th>
      </tr></thead>
      <tbody>
      <?php foreach ($users as $u): ?>
        <tr data-name="<?= $h(mb_strtolower($u['name'])) ?>" data-office="<?= $h($u['office']) ?>"
            data-working="<?= (int) $u['working'] ?>" data-present="<?= (int) $u['present'] ?>" data-absent="<?= (int) $u['absent'] ?>"
            data-late="<?= (int) $u['late'] ?>" data-latemin="<?= (int) $u['lateMin'] ?>" data-leave="<?= (int) $u['leave'] ?>"
            data-noout="<?= (int) $u['noOut'] ?>" data-avgin="<?= (int) ($u['avgIn'] ?? 99999) ?>" data-hours="<?= (int) $u['workedSec'] ?>">
          <td class="l"><a href="<?= $h($url(['user_id' => $u['id']])) ?>"><?= $h($u['name']) ?></a>
            <?php if ($u['auto']): ?><span class="tag auto" title="<?= $h($u['auto']) ?>">auto</span><?php endif; ?>
            <?php if ($u['position'] || $u['joined']): ?><div class="muted"><?= $h($u['position']) ?><?= $u['joined'] ? ($u['position'] ? ' · ' : '') . 'joined ' . $h($d($u['joined'])->format('d M')) : '' ?></div><?php endif; ?></td>
          <td class="l muted"><?= $h($u['officeName']) ?></td>
          <td><?= (int) $u['working'] ?></td>
          <td class="num-ok"><?= (int) $u['present'] ?></td>
          <td class="<?= $u['absent'] ? 'num-bad' : '' ?>"><?= (int) $u['absent'] ?></td>
          <td class="<?= $u['late'] ? 'num-late' : '' ?>"><?= (int) $u['late'] ?></td>
          <td class="<?= $u['late'] ? 'num-late' : '' ?>"><?= $h($mins((int) $u['lateMin'])) ?></td>
          <?php if ($showLeave): ?><td><?= (int) $u['leave'] ?></td><?php endif; ?>
          <td class="<?= $u['noOut'] ? 'num-bad' : '' ?>"><?= (int) $u['noOut'] ?></td>
          <td><?= $h($secClock($u['avgIn'])) ?></td>
          <td><?= $h($hours($u['workedSec'])) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table></div>
    <div class="note">Present + Off<?= $showLeave ? ' + Leave' : '' ?> = Working days. Click a name for the day-by-day record, click a column title to sort.</div>
  <?php endif; ?>
  <div class="note">Settings (office hours, grace, holidays): /bitrix/php_interface/a7_attendance.config.php · Last updated <?= $h($now->format('h:i A')) ?>.</div>
</div>
<script>
(function () {
  var q = document.getElementById('q'), office = document.getElementById('office'), grid = document.getElementById('grid');
  if (!grid) return;
  var body = grid.tBodies[0];
  function filter() {
    var s = (q.value || '').trim().toLowerCase(), o = office.value;
    Array.prototype.forEach.call(body.rows, function (r) {
      r.style.display = (!s || r.dataset.name.indexOf(s) !== -1) && (!o || r.dataset.office === o) ? '' : 'none';
    });
  }
  q.addEventListener('input', filter);
  office.addEventListener('change', filter);
  var dir = {};
  Array.prototype.forEach.call(grid.tHead.rows[0].cells, function (th) {
    th.addEventListener('click', function () {
      var k = th.dataset.k, asc = dir[k] = !dir[k];
      var rows = Array.prototype.slice.call(body.rows);
      rows.sort(function (a, b) {
        var x = a.dataset[k], y = b.dataset[k];
        var nx = parseFloat(x), ny = parseFloat(y);
        var c = (isNaN(nx) || isNaN(ny)) ? String(x).localeCompare(String(y)) : nx - ny;
        return asc ? c : -c;
      });
      rows.forEach(function (r) { body.appendChild(r); });
    });
  });
})();
</script>
</body>
</html>
