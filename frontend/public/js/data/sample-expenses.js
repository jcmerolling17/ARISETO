// frontend/public/js/data/sample-expenses.js

import { isoDateFromToday } from '../utils/dates.js';

/**
 * Sample farm expenses (EXPENSE) and harvest income (HARVEST_RECORD) for the cycles in
 * sample-farm.js: last dry season (harvested, so it has income) and the current wet season
 * (not harvested yet, so no income). Category ids are EXPENSE_CATEGORIES in farm-options.js.
 *
 * Not in the data dictionary yet: quantity and unit; and whole-farm expenses, which have
 * cycle_id null and carry farm_id, season and season_year instead.
 *
 * Totals: dry season 2026 expenses ₱78,060 (Field A ₱36,600, Field B ₱40,260, whole farm
 * ₱1,200), income ₱214,900; wet season 2026 expenses so far ₱62,600 (Field A ₱32,990,
 * Field B ₱29,010, whole farm ₱600), income ₱0.
 */

const SEEDS = 1;
const FERTILIZER = 2;
const CHEMICALS = 3;
const LABOR = 4;
const EQUIPMENT = 5;
const FUEL = 6;
const OTHERS = 7;

let nextId = 1;

/** One expense recorded `daysAgo` days before today by the sample farmer (user_id 6). */
function expense(cycleId, daysAgo, categoryId, amount, description, quantity = null, unit = null) {
  return {
    expense_id: nextId++,
    cycle_id: cycleId,
    category_id: categoryId,
    recorded_by: 6,
    amount_php: amount,
    expense_date: isoDateFromToday(-daysAgo),
    description,
    quantity,
    unit,
  };
}

/** A whole-farm expense: no cycle, so it carries the farm and season instead. */
function farmExpense(season, seasonYear, daysAgo, categoryId, amount, description, quantity = null, unit = null) {
  return { ...expense(null, daysAgo, categoryId, amount, description, quantity, unit), farm_id: 1, season, season_year: seasonYear };
}

const DRY_YEAR = Number(isoDateFromToday(-200).slice(0, 4));
const WET_YEAR = Number(isoDateFromToday(-23).slice(0, 4));

export const sampleExpenses = {
  expenses: [
    // Last dry season: Field A corn (cycle 91)
    expense(91, 207, EQUIPMENT, 5000, 'Tractor rental for plowing', 5, 'hour'),
    expense(91, 200, SEEDS, 9600, 'Hybrid corn seeds', 2, 'bag'),
    expense(91, 200, FERTILIZER, 6800, 'Complete fertilizer (14-14-14)', 4, 'sack'),
    expense(91, 200, LABOR, 2400, 'Planting labor', 48, 'hour'),
    expense(91, 186, FERTILIZER, 4600, 'Urea for side-dressing', 3, 'sack'),
    expense(91, 183, LABOR, 1600, 'Weeding labor', 32, 'hour'),
    expense(91, 170, CHEMICALS, 1150, 'Insecticide for corn borers', 1, 'liter'),
    expense(91, 150, FUEL, 1550, 'Diesel for water pump', 25, 'liter'),
    expense(91, 83, LABOR, 3000, 'Harvesting labor', 60, 'hour'),
    expense(91, 82, OTHERS, 900, 'Empty sacks for shelled corn', 60, 'bag'),
    // Last dry season: Field B rice (cycle 92)
    expense(92, 226, SEEDS, 3800, 'Certified rice seeds', 2, 'bag'),
    expense(92, 214, EQUIPMENT, 6000, 'Hand tractor rental for puddling', 12, 'hour'),
    expense(92, 205, LABOR, 7500, 'Transplanting labor', 150, 'hour'),
    expense(92, 200, CHEMICALS, 850, 'Herbicide', 1, 'liter'),
    expense(92, 195, FERTILIZER, 6800, 'Complete fertilizer (14-14-14)', 4, 'sack'),
    expense(92, 180, LABOR, 2000, 'Weeding labor', 40, 'hour'),
    expense(92, 175, FERTILIZER, 3200, 'Urea top-dressing', 2, 'sack'),
    expense(92, 160, FUEL, 1860, 'Diesel for water pump', 30, 'liter'),
    expense(92, 98, EQUIPMENT, 7500, 'Combine harvester rental', 5, 'hour'),
    expense(92, 97, OTHERS, 750, 'Empty sacks for palay', 50, 'bag'),
    farmExpense('dry', DRY_YEAR, 96, OTHERS, 1200, 'Hauling harvest to MPMPC'),

    // Current wet season: Field A corn (cycle 101)
    expense(101, 30, EQUIPMENT, 5000, 'Tractor rental for plowing', 5, 'hour'),
    expense(101, 23, SEEDS, 9800, 'Hybrid corn seeds', 2, 'bag'),
    expense(101, 23, FERTILIZER, 7000, 'Complete fertilizer (14-14-14)', 4, 'sack'),
    expense(101, 23, LABOR, 2400, 'Planting labor', 48, 'hour'),
    expense(101, 9, FERTILIZER, 4800, 'Urea for side-dressing', 3, 'sack'),
    expense(101, 6, LABOR, 1600, 'Weeding labor', 32, 'hour'),
    expense(101, 5, FUEL, 1240, 'Diesel for water pump', 20, 'liter'),
    expense(101, 1, CHEMICALS, 1150, 'Insecticide for corn borers', 1, 'liter'),
    // Current wet season: Field B rice (cycle 102)
    expense(102, 61, SEEDS, 3800, 'Certified rice seeds', 2, 'bag'),
    expense(102, 52, EQUIPMENT, 6000, 'Hand tractor rental for puddling', 12, 'hour'),
    expense(102, 40, LABOR, 7500, 'Transplanting labor', 150, 'hour'),
    expense(102, 35, CHEMICALS, 850, 'Herbicide', 1, 'liter'),
    expense(102, 30, FERTILIZER, 7000, 'Complete fertilizer (14-14-14)', 4, 'sack'),
    expense(102, 15, LABOR, 2000, 'Weeding labor', 40, 'hour'),
    expense(102, 10, FUEL, 1860, 'Diesel for water pump', 30, 'liter'),
    farmExpense('wet', WET_YEAR, 24, OTHERS, 600, 'Hauling fertilizer from MPMPC'),
  ],
  harvests: [
    { harvest_id: 1, cycle_id: 91, harvest_date: isoDateFromToday(-83), quantity_kg: 5600, unit_price_php: 17, gross_income_php: 95200 },
    { harvest_id: 2, cycle_id: 92, harvest_date: isoDateFromToday(-98), quantity_kg: 6300, unit_price_php: 19, gross_income_php: 119700 },
  ],
};

export const emptyExpenses = {
  expenses: [],
  harvests: [],
};
