"""
Playwright E2E tests for authentication flows.
Tests: login failures, session handling, role-based UI hiding.
"""

import { test, expect } from '@playwright/test'

test.describe('Authentication & RBAC UI', () => {
  test('I1 - Login with wrong password shows error', async ({ page }) => {
    await page.goto('/login')
    await page.fill('[data-testid="email"]', 'user@candata.ai')
    await page.fill('[data-testid="password"]', 'wrongpassword')
    await page.click('[data-testid="login-submit"]')

    // Assert: error message visible
    await expect(page.locator('[data-testid="login-error"]')).toBeVisible()
    // Assert: NOT redirected to dashboard
    await expect(page).not.toHaveURL(/dashboard/)
  })

  test('I2 - Viewer cannot see approve button', async ({ page }) => {
    // Mock: Login as Viewer
    await page.goto('/recommendations')
    // Simulate Viewer token in localStorage
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'viewer-token-test')
      localStorage.setItem('user_role', 'Viewer')
    })
    await page.reload()

    // Assert: no approve/reject buttons visible
    await expect(page.locator('[data-testid="btn-approve"]')).not.toBeVisible()
    await expect(page.locator('[data-testid="btn-reject"]')).not.toBeVisible()
  })

  test('I3 - Viewer cannot upload (button hidden/disabled)', async ({ page }) => {
    // Mock Viewer login
    await page.goto('/uploads')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'viewer-token-test')
      localStorage.setItem('user_role', 'Viewer')
    })
    await page.reload()

    const uploadBtn = page.locator('[data-testid="btn-upload"]')

    // Either hidden or disabled
    const isHidden = !(await uploadBtn.isVisible())
    const isDisabled = await uploadBtn.isDisabled().catch(() => true)

    expect(isHidden || isDisabled).toBe(true)
  })

  test('I4 - Upload wrong file type shows UI error before API call', async ({ page }) => {
    // Mock Analyst login
    await page.goto('/uploads')
    await page.evaluate(() => {
      localStorage.setItem('auth_token', 'analyst-token-test')
      localStorage.setItem('user_role', 'Analyst')
    })
    await page.reload()

    // Attempt to upload .xlsx file
    await page.setInputFiles('[data-testid="file-input"]', {
      name: 'test.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('PK\\x03\\x04'),
    })

    // Assert: UI error shown
    await expect(page.locator('[data-testid="upload-error"]')).toBeVisible()
  })
})
