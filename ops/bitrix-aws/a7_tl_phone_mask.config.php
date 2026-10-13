<?php
/**
 * Phone-mask config: last-4 hide + eye unlock (password admin222007).
 *
 * Applies to:
 *  - users listed under "leaders" (Team Leads + explicit mask-only), OR
 *  - anyone in auto_department_ids (Admin & Finance dept 2 + subdepts),
 * except exempt_user_ids (full numbers).
 */
return [
    'password' => 'admin222007',
    'reveal_seconds' => 30,
    // Admin & Finance — recursive. Future joiners get the mask automatically.
    'auto_department_ids' => [2],
    // Full numbers: Admin Abdul Malik + company account.
    'exempt_user_ids' => [1, 2237],
    // Explicit mask (not via dept auto) — IT / developers etc.
    'extra_mask_user_ids' => [
        2311, // Matloob Ul Hassnain
        2558, // khadija Munir
        2637, // Shahbaz Elahi (IT Head)
        2379, // eman Fazal — Bitrix Administrator; lead phones were fully visible
    ],
    'leaders' => [
        // Team heads (Excel final)
        2560 => [
            'name' => 'Hassan',
            'email' => 'hassan.a7group@gmail.com',
            'department_id' => 69,
            'agents' => [2344, 2429, 2380, 2376, 2434, 2291],
        ],
        2551 => [
            'name' => 'Hussnain',
            'email' => 'Ranahussnain.a7group@gmail.com',
            'department_id' => 70,
            'agents' => [2369, 2381, 2371, 2535, 2368, 2367, 2350],
        ],
        2297 => [
            'name' => 'Jaweria',
            'email' => 'javeriabibi.a7group@gmail.com',
            'department_id' => 71,
            'agents' => [2302, 2298, 2299, 2390, 2392],
        ],
        // Mask-only — no access/permission changes (non–Admin-Finance)
        2319 => [
            'name' => 'Amna Khan',
            'email' => 'Hra7grouprealestate@gmail.com',
            'department_id' => 58,
            'agents' => [],
        ],
        454 => [
            'name' => 'Hina Sultan',
            'email' => 'hinasultan.anwaralriyadh@gmail.com',
            'department_id' => 43,
            'agents' => [],
        ],
        2628 => [
            'name' => 'HR Usman',
            'email' => 'usman.a7group@gmail.com',
            'department_id' => 58,
            'agents' => [],
        ],
        2632 => [
            'name' => 'Furqan Khalid',
            'email' => 'furqan.a7group@gmail.com',
            'department_id' => 58,
            'agents' => [],
        ],
        // Raoof / Sreya are in Admin & Finance (dept 2) — covered by auto_department_ids.
    ],
];
