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

/** When a crop calendar task reminds the farmer. */
export const REMINDER_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'at_start', label: 'At start time' },
  { value: '30_min', label: '30 minutes before' },
  { value: '1_hour', label: '1 hour before' },
  { value: '1_day', label: '1 day before' },
];
