<?php
/**
 * Phone-mask config: last-4 hide + eye unlock (password admin222007).
 * Applies ONLY to users listed under "leaders".
 * Agents / others are not listed → full numbers.
 */
return [
    'password' => 'admin222007',
    'reveal_seconds' => 30,
    'leaders' => [
        // Team heads (Excel final)
        2560 => [
            'name' => 'Hassan',
            'email' => 'hassan.a7group@gmail.com',
            'department_id' => 69,
            'agents' => [2344, 2429, 2379, 2380, 2376, 2434, 2291],
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
        // Mask-only — no access/permission changes
        2319 => [
            'name' => 'Amna Khan',
            'email' => 'Hra7grouprealestate@gmail.com',
            'department_id' => 58,
            'agents' => [],
        ],
        2191 => [
            'name' => 'Raoof Ahmad',
            'email' => 'ar.property86@gmail.com',
            'department_id' => 15,
            'agents' => [],
        ],
        454 => [
            'name' => 'Hina Sultan',
            'email' => 'hinasultan.anwaralriyadh@gmail.com',
            'department_id' => 43,
            'agents' => [],
        ],
        2257 => [
            'name' => 'Sreya Gopi',
            'email' => 'gopisreya78@gmail.com',
            'department_id' => 2,
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
    ],
];
