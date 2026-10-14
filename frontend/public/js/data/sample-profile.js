// frontend/public/js/data/sample-profile.js

/**
 * Sample signed-in member (USER). barangay_name is the name of USER.barangay_id, as the
 * profile would show it. The farm's plots come from sample-farm.js. The empty version is a
 * member who has not set up a farm yet (no email, no barangay).
 */
export const sampleProfile = {
  user: {
    user_id: 6,
    member_no: 'MPMPC-0042',
    first_name: 'Juan',
    last_name: 'Dela Cruz',
    mobile_no: '+639171234567',
    email: 'juan.delacruz@example.com',
    role: 'member',
    municipality: 'Mamburao',
    barangay_name: 'Tangkalan',
    preferred_language: 'en',
    account_status: 'active',
  },
};

export const emptyProfile = {
  user: {
    user_id: 6,
    member_no: 'MPMPC-0042',
    first_name: 'Juan',
    last_name: 'Dela Cruz',
    mobile_no: '+639171234567',
    email: null,
    role: 'member',
    municipality: 'Mamburao',
    barangay_name: null,
    preferred_language: 'en',
    account_status: 'active',
  },
};
