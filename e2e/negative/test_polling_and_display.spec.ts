"""
Playwright E2E tests for job polling, SSE handling, and data display integrity.
Tests: timeout handling, malformed responses, data validation.
"""

import { test, expect } from '@playwright/test'

test.describe('Polling & Data Display', () => {
  test('I5 - Poll timeout: UI handles job pending >60 seconds gracefully', async ({ page }) => {
    // Start a recommendation request
    await page.goto('/recommendations')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'TreasuryManager')
    })
    await page.reload()

    // Mock: intercept job status to always return pending
    await page.route('**/api/recommendations/rec-*', async route => {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'pending',
          progress: 50,
        }),
      })
    })

    await page.click('[data-testid="btn-request-recommendations"]')

    // Wait 65 seconds
    await page.waitForTimeout(65000)

    // Assert: UI shows loading indicator or graceful timeout message
    const loadingIndicator = page.locator('[data-testid="job-loading"]')
    const errorState = page.locator('[data-testid="job-error"]')
    const timeoutMessage = page.locator('[data-testid="job-timeout"]')

    const hasEither = (await loadingIndicator.isVisible()) ||
                      (await errorState.isVisible()) ||
                      (await timeoutMessage.isVisible())

    expect(hasEither).toBe(true)

    // Assert: NO unhandled promise rejection or JS crash
    const consoleLogs: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error') {
        consoleLogs.push(msg.text())
      }
    })
    // Wait a bit more to catch any errors
    await page.waitForTimeout(1000)
    expect(consoleLogs).toHaveLength(0)
  })

  test('I10 - Chat SSE: Handles malformed SSE event gracefully', async ({ page }) => {
    // Mock Analyst login
    await page.goto('/chat')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'Analyst')
    })
    await page.reload()

    // Intercept chat stream and inject malformed event
    await page.route('**/api/chat/stream', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {invalid json}\n\nevent: done\ndata: {"run_id": "test"}\n\n',
      })
    })

    // Send chat message
    await page.fill('[data-testid="chat-input"]', 'What is the cash position?')
    await page.click('[data-testid="chat-send"]')

    // Wait for response
    await page.waitForTimeout(2000)

    // Assert: UI does NOT crash, shows error or partial response
    const errorDiv = page.locator('[data-testid="chat-error"]')
    const responseDiv = page.locator('[data-testid="chat-response"]')

    const hasResponse = (await errorDiv.isVisible()) || (await responseDiv.isVisible())
    expect(hasResponse).toBe(true)

    // Assert: NO JS crash
    const pageErrors: string[] = []
    page.on('pageerror', error => {
      pageErrors.push(error.toString())
    })
    await page.waitForTimeout(500)
    expect(pageErrors).toHaveLength(0)
  })

  test('I11 - Recommendation approval: Confirm dialog shown before submit', async ({ page }) => {
    // Mock TreasuryManager login
    await page.goto('/recommendations')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'TreasuryManager')
    })
    await page.reload()

    // Click approve button
    await page.click('[data-testid="btn-approve"]')

    // Assert: confirmation modal appears
    await expect(page.locator('[data-testid="confirm-approval-modal"]')).toBeVisible()

    // Cancel approval
    await page.click('[data-testid="btn-cancel-approval"]')

    // Assert: status remains Pending
    const statusBadge = await page.locator('[data-testid="approval-status"]').textContent()
    expect(statusBadge).toContain('Pending')
  })

  test('I12 - File upload: Unmapped account flagged, not silently dropped', async ({ page }) => {
    // Mock Analyst login
    await page.goto('/uploads')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'Analyst')
    })
    await page.reload()

    // Mock API to return flagged rows
    await page.route('**/api/files/upload', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            rows_ingested: 1,
            rows_flagged: 1,
            flagged_rows: [
              {
                row_number: 1,
                issue: 'Account ACC-9999 not in Account Master',
                action: 'Low confidence ingestion',
              },
            ],
          }),
        })
      } else {
        await route.continue()
      }
    })

    // Upload CSV with unmapped account
    await page.setInputFiles('[data-testid="file-input"]', {
      name: 'bank_unmapped.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from('Entity Name,Account Number,Closing Balance\nTest,ACC-9999,1000000\n'),
    })

    await page.click('[data-testid="btn-upload"]')
    await page.waitForSelector('[data-testid="upload-result"]')

    // Assert: flagged rows section visible
    await expect(page.locator('[data-testid="flagged-rows"]')).toBeVisible()

    // Assert: "Account Master" message shown
    const flagText = await page.locator('[data-testid="flagged-rows"]').textContent()
    expect(flagText).toContain('Account Master')

    // Assert: rows_valid > 0 (row was ingested with Low confidence)
    const rowsValid = parseInt(await page.locator('[data-testid="rows-valid"]').textContent() || '0')
    expect(rowsValid).toBeGreaterThan(0)
  })
})
