// frontend/public/js/data/farm-options.js

import { t, hasText } from '../i18n/i18n.js';

/** The 11 Occidental Mindoro municipalities (users.municipality, BARANGAY.municipality). */
export const MUNICIPALITIES = [
  'Abra de Ilog',
  'Calintaan',
  'Looc',
  'Lubang',
  'Magsaysay',
  'Mamburao',
  'Paluan',
  'Rizal',
  'Sablayan',
  'San Jose',
  'Santa Cruz',
];

/** CROP_CYCLE.season */
export const SEASONS = [
  { value: 'wet', get label() { return t('season.wet'); } },
  { value: 'dry', get label() { return t('season.dry'); } },
];

/** The season the app suggests (Section 4): 'wet' from June to November, 'dry' otherwise. */
export function suggestedSeason(today = new Date()) {
  const month = today.getMonth() + 1;
  return month >= 6 && month <= 11 ? 'wet' : 'dry';
}

/** Crops a field can be planted with during farm setup; icon is the sprite symbol id. */
export const CROPS = [
  { value: 'rice', label: 'Rice', icon: 'icon-crop-rice' },
  { value: 'corn', label: 'Corn', icon: 'icon-crop-corn' },
  { value: 'onion', label: 'Onion', icon: 'icon-crop-onion' },
];

/** Growth stage of a crop calendar task, in season order (headings of the weekly timeline). */
export const GROWTH_STAGES = [
  { value: 'land_preparation', get label() { return t('stage.land_preparation'); } },
  { value: 'seed_sowing', get label() { return t('stage.seed_sowing'); } },
  { value: 'vegetative', get label() { return t('stage.vegetative'); } },
  { value: 'reproductive', get label() { return t('stage.reproductive'); } },
  { value: 'harvest', get label() { return t('stage.harvest'); } },
];

/** EXPENSE_CATEGORY rows; icon is the sprite symbol id, color the chart color. */
export const EXPENSE_CATEGORIES = [
  { category_id: 1, category_name: 'Seeds', icon: 'icon-seeds', color: '#e0475a' },
  { category_id: 2, category_name: 'Fertilizer', icon: 'icon-fertilizer', color: '#f28aa0' },
  { category_id: 3, category_name: 'Chemicals', icon: 'icon-chemicals', color: '#b8306e' },
  { category_id: 4, category_name: 'Labor', icon: 'icon-labor', color: '#7e57c2' },
  { category_id: 5, category_name: 'Equipment', icon: 'icon-equipment', color: '#43a047' },
  { category_id: 6, category_name: 'Fuel', icon: 'icon-fuel', color: '#2a9fd6' },
  { category_id: 7, category_name: 'Others', icon: 'icon-others', color: '#f39233' },
];

/** An expense category's name in the current language (the stored name when unknown). */
export function categoryLabel(name) {
  return hasText(`category.${name}`) ? t(`category.${name}`) : name;
}

/** Units an expense quantity can be entered in. */
export const QUANTITY_UNITS = [
  { value: 'kg', get label() { return t('unit.kg'); } },
  { value: 'sack', get label() { return t('unit.sack'); } },
  { value: 'liter', get label() { return t('unit.liter'); } },
  { value: 'bag', get label() { return t('unit.bag'); } },
  { value: 'hour', get label() { return t('unit.hour'); } },
];
