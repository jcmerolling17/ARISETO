// frontend/public/js/data/sample-notifications.js

/**
 * Sample notifications. Weather alerts follow WEATHER_ALERT (message, severity, issued_at);
 * the other kinds (task reminders, yield and diagnosis updates, growth stages, account news)
 * have no table in the data dictionary yet, so they share this shape:
 * { notification_id, type, title, message, severity, issued_at, is_read }.
 * Times are counted back from now so "Just now" and "20m ago" stay true.
 * Each item matches the other sample files (calendar tasks, yield estimate, Field A diagnosis).
 */

function minutesAgo(minutes) {
  return new Date(Date.now() - minutes * 60 * 1000).toISOString();
}

const HOUR = 60;
const DAY = 24 * HOUR;

export const sampleNotifications = {
  notifications: [
    {
      notification_id: 6,
      type: 'weather_alert',
      title: 'Heavy Rain Expected',
      message: 'Heavy rain is likely in Tangkalan tomorrow from 2:00 PM to 5:00 PM. Apply fertilizer in the morning, before the rain.',
      severity: 'warning',
      issued_at: minutesAgo(1),
      is_read: false,
    },
    {
      notification_id: 5,
      type: 'task_reminder',
      title: 'Today’s Task',
      message: 'Scout for corn borers in Field A at 3:00 PM.',
      severity: 'info',
      issued_at: minutesAgo(20),
      is_read: false,
    },
    {
      notification_id: 4,
      type: 'yield_estimate',
      title: 'Yield Estimate Update',
      message: 'New estimate for Field A (Corn): 6.25 tons, or 5.0 tons per hectare.',
      severity: 'info',
      issued_at: minutesAgo(1 * HOUR),
      is_read: false,
    },
    {
      notification_id: 3,
      type: 'diagnosis',
      title: 'Leaf Blight Detected',
      message: 'Early signs of northern corn leaf blight were found in your Field A scan. View the treatment advice.',
      severity: 'warning',
      issued_at: minutesAgo(5 * HOUR),
      is_read: false,
    },
    {
      notification_id: 2,
      type: 'growth_stage',
      title: 'Growth Stage Reached',
      message: 'Corn in Field A has entered the vegetative phase.',
      severity: 'info',
      issued_at: minutesAgo(16 * DAY),
      is_read: true,
    },
    {
      notification_id: 1,
      type: 'account',
      title: 'Account Approved',
      message: 'The MPMPC administrator approved your account. Welcome to ARISETO!',
      severity: 'info',
      issued_at: minutesAgo(210 * DAY),
      is_read: true,
    },
  ],
};

export const emptyNotifications = {
  notifications: [],
};
