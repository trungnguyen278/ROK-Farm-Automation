# Gem Flow Test Log

> Live log cho flow dao gem qua ESP32 HID. Cap nhat ngay sau moi lan thu de giu ngu canh khi bi gioi han quota.

## Quy tac an toan click

- Chi dieu khien chuot qua ESP32 serial, khong dung OS mouse automation.
- Khong click neu chua capture duoc game window.
- Khong click neu template target khong match tren frame hien tai.
- Moi target click phai theo pattern: `MOVETO -> re-capture -> verify target con dung vi tri -> CLICK`.
- Neu target bien mat hoac lech qua 20px sau `MOVETO`, re-find va re-aim. Neu re-find fail thi dung step.
- Moi step phai luu screenshot vao `tools/screenshots/gem_farm_test/` va log vao `logs/gem_farm_test_*.log`.

## Flow can xac nhan

1. Detect game window va ket noi ESP32.
2. Detect state hien tai, dua ve world map neu can.
3. Tim gem mine bang `resources/gem_mine_close`, fallback `resources/gem_mine`.
4. `MOVETO` vao gem mine, capture lai, verify mine van dung vi tri, roi `CLICK`.
5. Tim va verify `buttons/gather_btn`, roi click.
6. Neu panel chon doi hien ra, tim va verify `buttons/new_troop_btn`, roi click.
7. Tim va verify march button: uu tien `buttons/march_btn_orange`, fallback `buttons/march_btn`, roi click.
8. Verify march da bat dau va dua ve city/world state on dinh.

## Lich su thu gan nhat

| Time | Tool | Result | Evidence | Note |
|---|---|---|---|---|
| 2026-05-15 18:47 | `python -m tools.test_gem_farm_flow --port COM27` | FAIL | `logs/gem_farm_test_20260515_184755.log`, `tools/screenshots/gem_farm_test/step2_not_found_184825.png` | Tim state city OK, nhung sau zoom state unknown; scan khong tim gem. Co `DRAG` timeout 3 retries. |
| 2026-05-15 18:53 | `python -m tools.test_gem_farm_flow --port COM27` | PARTIAL PASS | `logs/gem_farm_test_20260515_185329.log`, `tools/screenshots/gem_farm_test/step5_after_march_click_185355.png` | Tim gem, click gem, click gather, click march deu co screenshot. Final verify van `unknown`, nen chua coi la confirmed 100%. |
| 2026-05-15 19:27 | Preflight no-click | PASS with warning | `tools/screenshots/gem_farm_test/preflight_current_192735.png` | ESP32 COM27 connect + PING OK. Current screen has visible gem candidate. Found issue: old `gather_btn.png` false-positive 0.704 because template was wrong crop. |
| 2026-05-15 19:37 | Template/tool hardening | PASS | `templates/buttons/gather_btn.png`, `tests/test_action_executor.py` | Re-cropped `gather_btn.png` from real gem popup. Added confidence/play-area gates in `tools/test_gem_farm_flow.py` and `logic/action_executor.py`. Unit test: 50 passed. Current no-popup gather false-positive dropped to 0.338. |
| 2026-05-15 19:38 | Live run via ESP32 HID | PARTIAL PASS | `logs/gem_farm_test_20260515_193853.log`, `tools/screenshots/gem_farm_test/step4_after_gather_click_193904.png` | Passed gem detect, MOVETO verify drift 0px, click gem, click real `THU THAP`. Failed at march because game opened `Quân mới` selection panel, not march dialog. |
| 2026-05-15 19:42 | Continue from troop panel | PARTIAL PASS | `tools/screenshots/gem_farm_test/continue_after_new_troop_194220.png` | Captured/clicked `buttons/new_troop_btn` successfully. Discovered next screen has orange `HÀNH QUÂN` button, old blue `march_btn` does not match. |
| 2026-05-15 19:45 | Continue orange march | PASS | `tools/screenshots/gem_farm_test/continue2_after_march_194521.png` | Captured/clicked `buttons/march_btn_orange` via ESP32. Final screenshot shows route dots to gem and queue `4/4`, confirming single gem march flow. |
| 2026-05-16 | Find-only preflight | PASS | inline `ActionExecutor` preflight | New gem-search flow normalized current state via ESP32 HID and found `resources/gem_mine_close` at frame `(870, 295)`, conf=0.702. No gem/gather click was sent. |
| 2026-05-16 02:00 | Live harvest run 1 | PASS | `tools/screenshots/gem_farm_test/continue_run1_after_march_020047.png` | Started from city/world-map unknown state, found gem, clicked `Thu Thập`, selected troop, manually continued orange `Hành Quân`. Screenshot shows green march route and queue `3/4`. |
| 2026-05-16 02:22 | Live harvest run 2 | BLOCKED | `wide_scan2_no_far_west_022338.png` and related `run2_*` screenshots | Second attempt repeatedly found only the already-occupied gem (`TRIỆU HỒI`, `Số lượng thu thập: 1/10`) or no verified gem candidate after wide sweep. Search panel did not expose a gem category. |

## Dang lam

- Single-mine gem flow da duoc xac nhan qua ESP32 HID: gem node -> `THU THAP` -> `Quân mới` -> orange `HÀNH QUÂN`.
- Next: chay lai `tools/test_gem_farm_flow.py` tu dau khi co gem/troop slot moi de xac nhan full script mot mach, sau do moi lam loop nhieu mo.
- `ActionExecutor` now has a reusable gem-search flow: visible-gem check first, unknown-state recovery with Space/Escape, controlled 5-step zoom-out, then ESP32 DRAG scan.
- Latest live run confirmed one more gem march. Two-slot test is blocked by map availability, not ESP32/control path: no second actionable gem was found with confirmed templates.

## Blockers / dieu can theo doi

- `states/march_screen`, `popups/march_confirm`, `states/commander_select`, `states/alliance_screen` chua co template, co the lam final state bi `unknown`.
- `states/city_view`/`states/world_map` dang dua nhieu vao bottom bar nen co the mislabel world map. Live gem flow khong duoc dua vao state label de click; phai dua vao verified action templates.
- Full script mot mach chua re-run sau khi them `new_troop_btn` va `march_btn_orange` vi current troop slot da duoc dung cho lan confirm.
- `DRAG` tung timeout o lan 18:47; can xac nhan firmware/ACK timeout hien tai da on dinh.
- Final success criterion nen la: click march ACK + screenshot sau march cho thay UI da chuyen trang/thanh cong, khong chi dua vao `StateDetector` neu state template con thieu.
- `resources/gem_mine_v2` produced a forest false-positive at conf=0.721 on 2026-05-16; do not let it drive clicks until recaptured/validated.
