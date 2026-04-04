# SubsidyAI — E2E Test Report

**Date:** 2026-04-04  
**URL:** `https://subsidyai.109-235-119-92.sslip.io`  
**Test Plan:** [E2E_TEST_PLAN.md](../E2E_TEST_PLAN.md)

## Summary

| Metric | Value |
|--------|-------|
| Total scenarios | 18 |
| Passed | 10 |
| Failed | 6 |
| Skipped | 2 |
| Bugs found | 5 |

---

## Critical Bugs (Blockers)

### BUG-001: ECP login does not work (farmer role)
- **Severity:** CRITICAL
- **Scenarios blocked:** S1.1-S1.9, S6.1, S7.3, S9.1-S9.4, S10.1-S10.3
- **Steps to reproduce:**
  1. Go to `/auth/login/`
  2. Select "Вход через ЭЦП" tab
  3. Enter any demo IIN (e.g. `880720300456`)
  4. Click "Подписать и войти через ЭЦП"
- **Expected:** Redirect to `/dashboard/` with farmer role
- **Actual:** Page stays on `/auth/login/`, no navigation occurs
- **Impact:** Blocks **60% of all test scenarios** — entire applicant flow, notifications, API tests, full cycle tests
- **Screenshot:** [s1_1_login_fail.png](004_s1_1_login_fail.png)

---

## Medium Bugs

### BUG-002: `/commission/batch/` returns server error
- **Severity:** MEDIUM
- **Scenario:** S3.3
- **Steps:** Login as `commission`, navigate to `/commission/batch/`
- **Expected:** Page loads with batch decision interface
- **Actual:** `net::ERR_HTTP_RESPONSE_CODE_FAILURE` (HTTP 500 or 404)
- **Recommendation:** Implement or fix the batch decision view

### BUG-003: `/model-info/` access denied for auditor
- **Severity:** MEDIUM
- **Scenario:** S5.2
- **Steps:** Login as `auditor`, navigate to `/model-info/`
- **Expected:** ML model info page (version, R2, accuracy, top features)
- **Actual:** "Нет доступа — У вашей роли (Аудитор) нет прав для просмотра этой страницы"
- **Screenshot:** [s5_2_model.png](016_s5_2_model.png)
- **Recommendation:** Add `auditor` to `allowed_roles` for the model-info view

### BUG-004: No approve/reject buttons on application detail (specialist)
- **Severity:** MEDIUM
- **Scenario:** S2.4
- **Steps:** Login as `specialist`, open any application detail page
- **Expected:** Buttons "Одобрить" / "Отклонить" / "На доработку"
- **Actual:** No decision buttons found
- **Note:** Buttons may only appear for applications with `checking` status. Test may have opened an application with a different status. Verify that at least some applications show decision controls.

### BUG-005: PDF export button missing
- **Severity:** MEDIUM
- **Scenario:** S8.1
- **Steps:** Login as `specialist`, open application detail from `/scoring/`
- **Expected:** Button/link "PDF" or "Скачать PDF"
- **Actual:** No PDF button found on the page
- **Recommendation:** Add PDF export functionality to `/applications/<id>/`

---

## Passed Scenarios

| ID | Name | Details |
|----|------|---------|
| S7.1 | Unauthorized access redirect | `/dashboard/` and `/applications/new/` correctly redirect to `/auth/login/` |
| S7.2 | Wrong password rejection | Login stays on `/auth/login/` with error message |
| S2.1 | Specialist dashboard | Stats: 2726 applications, 533 pending, 1156 approved (41.9%), avg score 73.6, budget 69.0B. Charts: score distribution + direction pie chart |
| S2.2 | Scoring ranking | Table with columns: #, number, applicant, IIN, direction, score, status, amount. Sorted by score descending |
| S2.3 | Application detail (scoring) | Hard Filters section, ML/Rule scoring, progress bars for 8 factors, recommendation |
| S2.5 | Specialist analytics | Analytics page loads with charts and statistics |
| S2.6 | Emulator | Entity list loads, clickable items with detail pages |
| S3.1 | Commission dashboard | Commission page loads with application list for review |
| S4.1 | Head dashboard + scoring | Dashboard loads, full access to scoring ranking |
| S5.1 | Audit log | Table with user actions, IPs, timestamps, action types with colored badges |

**Screenshots:**
- [Dashboard](005_s2_1_dashboard.png)
- [Scoring](006_s2_2_scoring.png)
- [Application detail](008_s2_3_detail.png)
- [Analytics](009_s2_5_analytics.png)
- [Emulator](010_s2_6_emulator.png)
- [Commission](012_s3_1_commission.png)
- [Head scoring](014_s4_1_scoring.png)
- [Audit log](015_s5_1_audit.png)

---

## Skipped / Blocked Scenarios

| ID | Name | Reason |
|----|------|--------|
| S1.1-S1.5 | Application submission (all types) | Blocked by BUG-001 (ECP login) |
| S1.6 | My farm (animals + land map) | Blocked by BUG-001 |
| S1.7 | RFID Dashboard | Blocked by BUG-001 |
| S1.8 | Farmer analytics | Blocked by BUG-001 |
| S1.9 | Farmer application list | Blocked by BUG-001 |
| S6.1 | Notifications | Blocked by BUG-001 |
| S7.3 | Role-based access control | Blocked by BUG-001 (needs farmer login) |
| S9.1-S9.4 | API endpoints | Blocked by BUG-001 |
| S10.1-S10.3 | Full cycle (submit -> score -> commission -> payment) | Blocked by BUG-001 |

---

## Recommendations (Priority Order)

1. **P0 — Fix ECP login** — This is the #1 blocker. Check the backend handler for ECP authentication. The JS animation may not complete, or the POST endpoint may not process the IIN correctly. Once fixed, re-run all blocked scenarios.
2. **P1 — Implement `/commission/batch/`** — Server error suggests the view/URL is missing or broken.
3. **P1 — Grant auditor access to `/model-info/`** — Add role to allowed list, or update test plan if intentional.
4. **P2 — Add PDF export button** — Missing from application detail page.
5. **P2 — Verify specialist decision buttons** — Ensure approve/reject buttons appear for `checking` status applications.
6. **P3 — Sync sidebar menu with role permissions** — Auditor sidebar doesn't show "AI Модель" link, but test plan expects access.

---

## Technical Notes

- All staff logins (specialist/commission/head/admin/auditor) work with password `demo123`
- ECP login uses demo IINs shown on login page (e.g. `880720300456` for approval scenario)
- Tests run with Playwright (Chromium, headless=false, 1920x1080)
- JSON report: [test_report.json](test_report.json)
- All screenshots saved in this directory
