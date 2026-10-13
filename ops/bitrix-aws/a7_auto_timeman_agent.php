<?php
/**
 * Bitrix agent entry for Matloob Auto Timeman.
 * Must return its own call string so the agent reschedules.
 *
 * Register once via deploy_auto_timeman.php:
 *   A7AutoTimemanAgent::run();
 */

require_once __DIR__ . '/a7_auto_timeman_lib.php';

class A7AutoTimemanAgent
{
    public static function run(): string
    {
        try {
            a7_auto_tm_tick();
        } catch (Throwable $e) {
            // Never break the agent chain.
        }
        return 'A7AutoTimemanAgent::run();';
    }
}
