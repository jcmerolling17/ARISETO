// frontend/public/js/utils/farm.js

import { SEASONS } from '../data/farm-options.js';

/** The cycle growing on a field now ('planned' or 'active'), or null. */
export function currentCycle(farm, fieldId) {
  return farm.cycles.find((c) => c.field_id === fieldId && (c.status === 'active' || c.status === 'planned')) ?? null;
}

/** 'Field A · Corn' (crop of the current cycle) or just 'Field A'. */
export function fieldLabel(farm, field) {
  const crop = currentCycle(farm, field.field_id)?.crop_name;
  return crop ? `${field.field_name} · ${crop}` : field.field_name;
}

/**
 * A season as { key: 'wet-2026', season, year, label: 'Wet season 2026', short: 'Wet 2026' };
 * a cycle's season year is its planting year.
 */
export function seasonOf(season, year) {
  const name = SEASONS.find((s) => s.value === season)?.label ?? season;
  return { key: `${season}-${year}`, season, year, label: `${name} ${year}`, short: `${name.split(' ')[0]} ${year}` };
}

export function cycleSeason(cycle) {
  return seasonOf(cycle.season, Number(cycle.planting_date.slice(0, 4)));
}

/** '₱62,600' or '-₱62,600'; whole pesos unless the amount has centavos. */
export function formatPeso(value) {
  const amount = Math.abs(value).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return `${value < 0 ? '-' : ''}₱${amount}`;
}
