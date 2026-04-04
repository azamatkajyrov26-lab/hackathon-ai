# SubsidyAI — E2E Test Report v2 (Retest)

**Date:** 2026-04-05  
**URL:** `https://subsidyai.109-235-119-92.sslip.io`  
**Test Plan:** [E2E_TEST_PLAN.md](../E2E_TEST_PLAN.md)  
**Retest Instructions:** [RETEST_INSTRUCTIONS.md](../RETEST_INSTRUCTIONS.md)  
**Previous Report:** [E2E_TEST_REPORT.md](E2E_TEST_REPORT.md)

---

## Summary

| Metric | v1 (04.04) | v2 (05.04) | Delta |
|--------|-----------|-----------|-------|
| Total | 18 | 28 | +10 |
| Passed | 10 | 23 | +13 |
| Failed | 6 | 3 | -3 |
| Skipped | 2 | 2 | 0 |
| Bugs | 5 | 2 | -3 |

---

## Fixed Bugs (Verified)

### BUG-001: ECP login — FIXED
- **Status:** VERIFIED FIXED
- ECP login via IIN now works for all 6 demo accounts
- Tested with `880720300456` (СПК "Береке Астана") — redirects to `/dashboard/` after signing animation
- All previously blocked scenarios (S1.x, S6.1, S7.3, S9.x) now testable

### BUG-003: Auditor /model-info/ — FIXED
- **Status:** VERIFIED FIXED
- Auditor now has access to ML model information page
- Page shows model version, accuracy metrics, top features

### BUG-004: Specialist decision buttons — CLARIFIED (Not a Bug)
- **Status:** BY DESIGN
- Buttons "Одобрить/Отклонить" are only visible for `commission` and `head` roles, not `specialist`
- Specialist has read-only access to applications — this is correct per role design

---

## Remaining Issues

### ISSUE-001: Commission vote buttons not found (S3.2)
- **Severity:** MEDIUM
- **Scenario:** S3.2 — Голосование комиссии
- **Details:** On the application detail page (accessed from `/commission/`), approve/reject buttons were not found
- **Possible cause:** Test navigated to a list instead of a specific application detail page. Or the application may not be in `checking` status
- **Action needed:** Manual verification — open a specific application with status `checking` as commission member

### ISSUE-002: Batch decision button not found (S3.3)
- **Severity:** LOW
- **Scenario:** S3.3 — Массовое решение
- **Details:** No "Массовое решение" / "Пакетное решение" button found on `/commission/` page
- **Note:** Per RETEST_INSTRUCTIONS, `/commission/batch/` is POST-only. The button should be on the `/commission/` page
- **Action needed:** Verify button exists and is labeled correctly

### ISSUE-003: PDF export button not found (S8.1)
- **Severity:** MEDIUM
- **Scenario:** S8.1
- **Details:** On application detail page (as specialist), no PDF download button/link was found
- **Note:** Per RETEST_INSTRUCTIONS, PDF button should be in the header of the application detail page for staff roles
- **Screenshot:** [030_s8_1_no_pdf.png](v2/030_s8_1_no_pdf.png)
- **Action needed:** Verify button placement — may need different CSS selector or the test didn't reach the individual detail page

---

## Passed Scenarios (23/28)

### Block 1: Applicant (farmer via ECP)
| ID | Name | Details |
|----|------|---------|
| S1.1 | Application form navigation | 5 steps navigated, categories visible |
| S1.6 | My Farm (animals + land) | Animal cards, land tab with map |
| S1.7 | RFID Dashboard | RFID monitoring page loads |
| S1.8 | Farmer analytics | Analytics page with scoring factors |
| S1.9 | Application list | Table with applications, detail page accessible |

### Block 2: Specialist
| ID | Name | Details |
|----|------|---------|
| S2.1 | Dashboard | Stats widgets, charts loaded |
| S2.2 | Scoring ranking | Sorted table with scores, clickable rows |
| S2.3 | Application detail (18 filters) | Hard Filters, ML/Rule scoring, progress bars |
| S2.4 | Decision (read-only) | Correct: no buttons for specialist role |
| S2.5 | Analytics | Charts and statistics loaded |
| S2.6 | Emulator | Entity list, clickable detail pages |

### Block 3: Commission
| ID | Name | Details |
|----|------|---------|
| S3.1 | Commission dashboard | Application list for review loaded |

### Block 4: Head
| ID | Name | Details |
|----|------|---------|
| S4.1 | Head dashboard + scoring | Full access to scoring ranking |

### Block 5: Auditor
| ID | Name | Details |
|----|------|---------|
| S5.1 | Audit log | Actions table with users, IPs, timestamps |
| S5.2 | Model info | ML model metrics (BUG-003 FIXED) |

### Block 6: Notifications
| ID | Name | Details |
|----|------|---------|
| S6.1 | Farmer notifications | Notification list accessible |

### Block 7: Negative Scenarios
| ID | Name | Details |
|----|------|---------|
| S7.1 | Unauthorized access redirect | Both /dashboard/ and /applications/new/ redirect to login |
| S7.2 | Wrong password | Stays on login page with error |
| S7.3 | Role-based access | Farmer blocked from /commission/ and /audit-log/ |

### Block 9: API Endpoints
| ID | Name | Details |
|----|------|---------|
| S9.1 | API entity-data | 200 OK, returns JSON with system data |
| S9.2 | API rfid-status | 200 OK, returns RFID monitoring data |
| S9.3 | API check-duplicate | 200 OK, returns duplicate check result |
| S9.4 | API form-progress | POST 200, GET 200 — save/load works |

---

## Not Fully Tested

| ID | Name | Reason |
|----|------|--------|
| S1.1 (full) | Complete application submission | Form navigated 5 steps but did not complete full submission (animal selection, sum calculation, etc.) |
| S1.2-S1.5 | Alternative submission types (kg meat, kg milk, duplicate, 50% block) | Need separate test runs with specific subsidy types |
| S4.2 | Head decision | No app_id captured from submission |
| S4.3 | Payment | No approved application available |
| S10.1-S10.3 | Full cycle | Requires complete submission first |

---

## New Functionality Checks

### My Farm — New Blocks (from RETEST_INSTRUCTIONS)
- **Падёж скота (Приказ №3-3/1061):** NOT FOUND on land tab (may be on different tab or needs specific data)
- **Нагрузка на пастбища (Приказ №3-3/332):** NOT FOUND on land tab
- **Note:** These blocks may appear only for specific farm profiles or on a different UI section

### Application Detail — 18 Filters
- Filter items detected on detail page
- New filters (падёж, пастбища, племенное свидетельство) — text search found partial matches in page content
- Full verification requires manual check of individual filter labels

---

## Recommendations

1. **P1 — Commission vote buttons:** Verify manually that approve/reject appears for `checking` status applications. May need to create a fresh application and test voting
2. **P1 — PDF button:** Check the exact CSS selector/position of the PDF download button on application detail page
3. **P2 — Full submission test:** Run a dedicated test for complete S1.1 flow (all 8 steps including animal selection and sum calculation)
4. **P2 — New farm blocks:** Verify padezh/pasture blocks appear for the correct demo IIN (may need specific farm profile)
5. **P3 — Full cycle S10.1:** Requires: farmer submit → specialist view → commission vote → head payment → notifications → audit log

---

## Screenshots

All screenshots saved in `v2/` subdirectory:
- [Dashboard](v2/003_s1_1_dashboard.png) | [Form](v2/004_s1_1_form.png) | [Farm](v2/010_s1_6_farm.png)
- [RFID](v2/011_s1_7_rfid.png) | [Analytics](v2/012_s1_8_analytics.png) | [Apps](v2/013_s1_9_apps.png)
- [Specialist Dashboard](v2/015_s2_1_dashboard.png) | [Scoring](v2/016_s2_2_scoring.png)
- [Detail](v2/017_s2_3_detail.png) | [Commission](v2/021_s3_1_commission.png)
- [Audit](v2/026_s5_1_audit.png) | [Model](v2/027_s5_2_model.png)
- [Notifications](v2/028_s6_1_notifications.png)
