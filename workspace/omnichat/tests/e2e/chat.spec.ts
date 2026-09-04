import { test, expect } from '@playwright/test';

test('chat message flow', async ({ page }) => {
  await page.goto('/');
  
  // Login simulieren (falls nötig)
  
  // Nachricht eingeben
  await page.fill('input[name="message"]', 'Hallo Team!');
  await page.click('button[type="submit"]');
  
  // Prüfen, ob Nachricht erscheint
  const message = page.locator('.message-content').last();
  await expect(message).toHaveText('Hallo Team!');
});
