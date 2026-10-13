<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    die();
}
/** @var array $arCurrentValues */
?>
<tr>
	<td align="right" width="40%">New Availability item id:</td>
	<td width="60%">
		<input type="text" name="target_item_id" value="<?= htmlspecialcharsbx((string)($arCurrentValues['target_item_id'] ?? '')) ?>" size="50">
		<div style="margin-top:4px;color:#6a737d;font-size:12px;">
			Use the Copy SPA return value, e.g. {=A75616_24296_97462_11513:ItemId}
		</div>
	</td>
</tr>
