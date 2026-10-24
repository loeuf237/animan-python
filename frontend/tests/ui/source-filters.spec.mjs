import { test, expect } from '@playwright/test'
import { mockApp } from './fixtures.mjs'

for (const width of [390, 1440]) {
  test(`single-choice source groups preserve filters from other groups at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 850 })
    await mockApp(page)
    await page.route('**/api/sources/aniyomi-long/filters', (route) =>
      route.fulfill({
        json: {
          tags: [
            { id: 'action', label: 'Action', group: 'Genres' },
            { id: 'vf', label: 'VF', group: 'Langue' },
            { id: 'vostfr', label: 'VOSTFR', group: 'Langue' },
          ],
          groups: [
            { name: 'Genres', single: false },
            { name: 'Langue', param: 'lang', single: true },
          ],
          orders: [{ id: 'source', label: 'Ordre de la source' }],
        },
      }),
    )
    const submitted = []
    await page.route('**/api/sources/aniyomi-long/catalogue?**', (route) => {
      submitted.push(new URL(route.request().url()).searchParams.getAll('tags'))
      return route.fulfill({
        json: { source: 'aniyomi-long', results: [], nextCursor: null, queryScope: 'catalogue' },
      })
    })
    await page.goto('/app/sources/aniyomi-long?mode=catalogue')
    await page.locator('.catalogue-tools > button').first().click()
    await page.getByRole('checkbox', { name: 'Action', exact: true }).check()
    await page.getByRole('checkbox', { name: 'VF', exact: true }).check()
    await page.getByRole('checkbox', { name: 'VOSTFR', exact: true }).check()
    await expect(page.getByRole('checkbox', { name: 'VF', exact: true })).not.toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'Action', exact: true })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'VOSTFR', exact: true })).toBeChecked()
    await page.getByRole('button', { name: 'Appliquer les filtres', exact: true }).click()
    await expect
      .poll(() =>
        submitted.some(
          (tags) => tags.length === 2 && tags.includes('action') && tags.includes('vostfr'),
        ),
      )
      .toBe(true)
  })
}
