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
