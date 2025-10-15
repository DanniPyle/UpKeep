# Images Directory

## Logo Files

### Required Logo:
- **File**: `logo-vertical.png`
- **Purpose**: Mobile/responsive version of the Keeply Home logo
- **Dimensions**: Recommended 200-300px width, vertical orientation
- **Format**: PNG with transparent background preferred

### Usage:
The landing page (`templates/index.html`) uses responsive logo switching:
- **Desktop (>768px)**: Horizontal logo from external URL
- **Mobile (≤768px)**: Vertical logo from `static/images/logo-vertical.png`

### To Add Your Vertical Logo:
1. Save your vertical logo as `logo-vertical.png` in this directory
2. Or update the path in `templates/index.html` line 292

### Current Setup:
- Desktop logo: External URL (horizontal version)
- Mobile logo: `{{ url_for('static', filename='images/logo-vertical.png') }}`
