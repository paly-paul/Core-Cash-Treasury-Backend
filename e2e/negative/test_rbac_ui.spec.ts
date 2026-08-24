"""
Playwright E2E tests for RBAC UI enforcement.
Tests: role-based button visibility, field restrictions, read-only enforcement.
"""

import { test, expect } from '@playwright/test'

test.describe('RBAC UI Enforcement', () => {
  test('I2 - Viewer role: Approve button not visible', async ({ page }) => {
    // Mock Viewer role
    await page.goto('/recommendations')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'Viewer')
    })
    await page.reload()

    // Assert: no approve/reject buttons
    await expect(page.locator('[data-testid="btn-approve"]')).not.toBeVisible()
    await expect(page.locator('[data-testid="btn-reject"]')).not.toBeVisible()
  })

  test('I3 - Viewer role: Upload tab disabled or hidden', async ({ page }) => {
    // Mock Viewer login
    await page.goto('/dashboard')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'Viewer')
    })
    await page.reload()

    // Try to navigate to uploads tab
    const uploadTab = page.locator('[data-testid="tab-uploads"]')
    const isTabHidden = !(await uploadTab.isVisible())

    if (!isTabHidden) {
      // If tab is visible, it should be disabled
      await expect(uploadTab).toHaveAttribute('disabled', 'true')
    }

    // If we can click it, the upload button should be disabled
    if (await uploadTab.isVisible()) {
      await uploadTab.click()
      const uploadBtn = page.locator('[data-testid="btn-upload"]')
      await expect(uploadBtn).toBeDisabled()
    }
  })

  test('I6 - OD Headroom never added to usable cash display', async ({ page }) => {
    // Setup: account with od_limit=2000000, usable_cash=8000000
    await page.goto('/dashboard')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'TreasuryManager')
    })
    await page.reload()

    // Get usable cash text
    const usableCashDisplay = await page.locator('[data-testid="usable-cash"]').textContent()

    // Assert: does NOT contain 10,000,000 (would be 8M + 2M od_limit)
    expect(usableCashDisplay).not.toContain('10,000,000')
    expect(usableCashDisplay).toContain('8,000,000')

    // Assert: OD Limit shown separately
    await expect(page.locator('[data-testid="od-limit-display"]')).toBeVisible()
  })

  test('I7 - Warning threshold shows yellow at 75% (not 80%)', async ({ page }) => {
    // Setup: account with min_threshold=1000000, current_balance=750000 (75%)
    await page.goto('/dashboard')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'TreasuryManager')
      // Mock account data
      sessionStorage.setItem('accounts', JSON.stringify([
        {
          id: 'ACC-001',
          balance: 750000,
          min_threshold: 1000000,
          status: 'yellow'
        }
      ]))
    })
    await page.reload()

    const accountRow = page.locator('[data-testid="account-row-ACC-001"]')
    const statusBadge = accountRow.locator('[data-testid="status-badge"]')

    // Assert: Yellow status (not red)
    await expect(statusBadge).toHaveClass(/yellow/)
    await expect(statusBadge).not.toHaveClass(/red/)
  })

  test('I8 - Variance display shows ±5% tolerance', async ({ page }) => {
    await page.goto('/forecast/variance')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'TreasuryManager')
    })
    await page.reload()

    // Assert: tolerance label shows ±5%
    const toleranceDisplay = await page.locator('[data-testid="variance-tolerance"]').textContent()
    expect(toleranceDisplay).toContain('5%')
    expect(toleranceDisplay).not.toContain('3%')
  })

  test('I9 - CFO Summary: MTD shown, no YTD label', async ({ page }) => {
    await page.goto('/cfo-summary')
    await page.evaluate(() => {
      localStorage.setItem('user_role', 'CFO')
    })
    await page.reload()

    // Assert: MTD visible
    await expect(page.locator('text=MTD')).toBeVisible()

    // Assert: YTD NOT visible
    const ytdElements = await page.locator('text=YTD').count()
    expect(ytdElements).toBe(0)
  })
})
