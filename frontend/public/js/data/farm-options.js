// frontend/public/js/data/farm-options.js

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
  { value: 'wet', label: 'Wet season' },
  { value: 'dry', label: 'Dry season' },
];

/** Crops a field can be planted with during farm setup; icon is the sprite symbol id. */
export const CROPS = [
  { value: 'rice', label: 'Rice', icon: 'icon-crop-rice' },
  { value: 'corn', label: 'Corn', icon: 'icon-crop-corn' },
  { value: 'onion', label: 'Onion', icon: 'icon-crop-onion' },
];

/** How a field was planted. */
export const PLANTING_METHODS = [
  { value: 'transplanting', label: 'Transplanting' },
  { value: 'direct_seeding', label: 'Direct seeding' },
];

/** Growth stage of a crop calendar task, in season order (headings of the weekly timeline). */
export const GROWTH_STAGES = [
  { value: 'land_preparation', label: 'Land Preparation' },
  { value: 'seed_sowing', label: 'Seed Sowing' },
  { value: 'vegetative', label: 'Vegetative Phase' },
  { value: 'reproductive', label: 'Reproductive Phase' },
  { value: 'harvest', label: 'Harvest' },
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

/** Disease detection: below this confidence the result is 'unrecognized' (tuned on the validation set). */
export const DIAGNOSIS_CONFIDENCE_THRESHOLD = 0.7;

/** Units an expense quantity can be entered in. */
export const QUANTITY_UNITS = [
  { value: 'kg', label: 'kg' },
  { value: 'sack', label: 'sack' },
  { value: 'liter', label: 'liter' },
  { value: 'bag', label: 'bag' },
  { value: 'hour', label: 'hour' },
];

/** When a crop calendar task reminds the farmer. */
export const REMINDER_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'at_start', label: 'At start time' },
  { value: '30_min', label: '30 minutes before' },
  { value: '1_hour', label: '1 hour before' },
  { value: '1_day', label: '1 day before' },
];
