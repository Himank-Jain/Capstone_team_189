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

test.beforeEach(async ({ page }) => {
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
