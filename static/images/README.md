# Images Directory

## Required Image Assets

### 1. Logo Files

#### **logo-vertical.png** (Required)
- **Purpose**: Mobile/responsive version of the Keeply Home logo
- **Dimensions**: Recommended 200-300px width, vertical orientation
- **Format**: PNG with transparent background preferred
- **Used in**: Landing page mobile view

#### **Usage:**
The landing page (`templates/index.html`) uses responsive logo switching:
- **Desktop (>768px)**: Horizontal logo from external URL
- **Mobile (≤768px)**: Vertical logo from `static/images/logo-vertical.png`

---

### 2. SEO & Social Media Images

#### **og-image.png** (Recommended)
- **Purpose**: Open Graph image for social media sharing (Facebook, LinkedIn, Twitter)
- **Dimensions**: 1200x630px (exact)
- **Format**: PNG or JPG
- **Used in**: `templates/base.html` meta tags
- **Shows when**: Someone shares your site on social media

---

### 3. Favicons (Recommended)

#### **favicon.ico**
- **Purpose**: Browser tab icon (legacy)
- **Dimensions**: 32x32px or 16x16px
- **Format**: ICO file
- **Used in**: `templates/base.html`

#### **favicon.svg**
- **Purpose**: Modern scalable favicon
- **Format**: SVG
- **Used in**: `templates/base.html`

#### **apple-touch-icon.png**
- **Purpose**: iOS home screen icon
- **Dimensions**: 180x180px
- **Format**: PNG
- **Used in**: `templates/base.html`

---

### 4. PWA Icons (Optional)

#### **icon-192.png**
- **Purpose**: Progressive Web App icon (small)
- **Dimensions**: 192x192px
- **Format**: PNG
- **Used in**: `static/site.webmanifest`

#### **icon-512.png**
- **Purpose**: Progressive Web App icon (large)
- **Dimensions**: 512x512px
- **Format**: PNG
- **Used in**: `static/site.webmanifest`

---

## Quick Setup Checklist

### Minimum (to remove console errors):
- [ ] Create placeholder `favicon.ico` (32x32px)
- [ ] Create placeholder `favicon.svg`
- [ ] Create placeholder `apple-touch-icon.png` (180x180px)
- [ ] Create placeholder `icon-192.png` and `icon-512.png`

### Recommended (for SEO):
- [ ] Create `og-image.png` (1200x630px) with your branding
- [ ] Add `logo-vertical.png` for mobile

### Optional (for polish):
- [ ] Use a favicon generator like https://realfavicongenerator.net/
- [ ] Create custom PWA icons with your brand colors

---

## Current Status

✅ **site.webmanifest** - Created  
⚠️ **favicon files** - Not yet created (causing 404 errors)  
⚠️ **og-image.png** - Not yet created (social sharing won't show image)  
⚠️ **PWA icons** - Not yet created (manifest references them)

---

## Quick Fix: Create Placeholders

If you want to remove the 404 errors quickly, you can:

1. **Comment out the favicon links** in `templates/base.html` (lines 12-15)
2. **Or** create simple placeholder images using any image editor
3. **Or** use an online favicon generator with your logo

The site will work fine without these - they're just nice-to-haves for polish and SEO.
