import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const routes = [
  { path: '/login', title: 'CAPSTONE-189', file: 'login' },
  { path: '/', title: 'SOC overview', file: 'dashboard' },
  { path: '/select-org', title: 'Select your organization', file: 'organization' },
  { path: '/alerts', title: 'Live alert feed', file: 'alerts' },
  { path: '/analytics', title: 'Analytics', file: 'analytics' },
  { path: '/entities/mock-resource', title: 'mock-resource', file: 'entity' },
  { path: '/demo', title: 'Live demo control', file: 'demo' },
  { path: '/settings', title: 'Settings', file: 'settings' },
  { path: '/users', title: 'Users', file: 'users' },
  { path: '/system-health', title: 'System health', file: 'system-health' },
  { path: '/model-health', title: 'Model health', file: 'model-health' },
  { path: '/onboarding', title: 'Onboarding', file: 'onboarding' },
  { path: '/connections', title: 'Connections', file: 'connections' },
  { path: '/incidents', title: 'Incidents & RCA', file: 'incidents' },
  { path: '/incidents/demo-high-confidence', title: 'vol-g00g', file: 'incident-detail' },
];

const screenshotDirectory = resolve(process.env.UI_SCREENSHOT_DIR || 'artifacts/ui-smoke');

test.beforeEach(async ({ page }, testInfo) => {
  // Signed-out flows must start without a stored session.
  if (testInfo.title.includes('/login') || testInfo.title.startsWith('account:')) return;
  await page.addInitScript(() => {
    localStorage.setItem('capstone.userId', 'mock-operator');
    localStorage.setItem('capstone.activeTenantId', 'google');
    localStorage.setItem('capstone.role', 'OPERATOR');
  });
});

for (const route of routes) {
  test(`renders ${route.path} in mock mode`, async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') pageErrors.push(message.text());
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(route.path);
    await expect(page.getByRole('heading', { name: route.title, exact: true })).toBeVisible();
    await page.waitForTimeout(200);
    await mkdir(screenshotDirectory, { recursive: true });
    await page.screenshot({
      path: resolve(screenshotDirectory, `${route.file}.png`),
      fullPage: true,
      animations: 'disabled',
    });
    expect(pageErrors).toEqual([]);
  });
}

test('completes synthetic onboarding and opens the demo control panel', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') pageErrors.push(message.text());
  });

  await page.goto('/onboarding');
  await page.getByLabel('Tenant name').fill('Acceptance synthetic tenant');
  await page.getByRole('button', { name: 'Create onboarding session' }).click();
  for (let index = 0; index < 6; index += 1) {
    await page.getByRole('button', { name: 'Mark step complete' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Enable monitoring' })).toBeVisible();
  await page.getByRole('button', { name: 'Complete setup' }).click();
  const demoLink = page.getByRole('link', { name: 'Run a demo scenario' });
  await expect(demoLink).toBeVisible();
  await demoLink.click();
  await expect(page.getByRole('heading', { name: 'Live demo control' })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('account: registers, sees itself as owner, and signs out', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/users');
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole('tab', { name: 'Create account' }).click();
  await page.getByLabel(/^Email/).fill('first.user@example.com');
  await page.getByLabel(/^Password/).fill('a-strong-pass');
  await page.getByLabel(/^Confirm password/).fill('a-strong-pass');
  await page.getByRole('button', { name: 'Create account' }).click();

  await expect(page.getByRole('heading', { name: 'Users', exact: true })).toBeVisible();
  await expect(page.getByLabel('Role for first.user@example.com')).toHaveValue('OWNER');
  await page.getByRole('link', { name: /Admin console/ }).click();
  await expect(page.getByLabel('Access for first.user@example.com')).toHaveValue('OWNER');
  await expect(page.getByText('first.user@example.com').first()).toBeVisible();

  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel(/^Email/).fill('first.user@example.com');
  await page.getByLabel(/^Password/).fill('wrong-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByText('Invalid email or password')).toBeVisible();
  await page.getByLabel(/^Password/).fill('a-strong-pass');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'SOC overview' })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('injecting a demo scenario raises an in-app notification', async ({ page }) => {
  await page.goto('/demo');
  await page.getByRole('button', { name: 'Inject scenario' }).click();
  await expect(page.getByText(/^New (LOW|MEDIUM|HIGH|CRITICAL) alert$/)).toBeVisible();
  await page.getByRole('button', { name: /Notifications, 1 unread/ }).click();
  await expect(page.getByRole('dialog', { name: 'Notifications' })).toContainText('vol-g00g');
  await page.screenshot({ path: resolve(screenshotDirectory, 'notifications.png') });
});
