---
name: Academic Modernist
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#444650'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#757681'
  outline-variant: '#c5c6d2'
  surface-tint: '#465c9b'
  primary: '#142d6a'
  on-primary: '#ffffff'
  primary-container: '#2e4482'
  on-primary-container: '#9eb3f9'
  inverse-primary: '#b4c5ff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#3c0092'
  on-tertiary: '#ffffff'
  tertiary-container: '#5517bf'
  on-tertiary-container: '#c1a8ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#2d4381'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#e9ddff'
  tertiary-fixed-dim: '#d0bcff'
  on-tertiary-fixed: '#23005c'
  on-tertiary-fixed-variant: '#5516be'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Public Sans
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Public Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Public Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Public Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
---

## Brand & Style

The design system is built for a professional e-learning environment that balances academic rigor with modern digital innovation. The personality is focused, reliable, and calm, minimizing cognitive load to prioritize learning and administrative efficiency.

The design style follows a **Modern Corporate** approach with a **Tactile** twist. It utilizes subtle depth, clear information hierarchy, and a refined use of whitespace to separate "Admin" functions from "Learning" experiences. Surfaces are layered to represent different levels of importance, using soft shadows and high-quality typography to establish a sense of stability and trust.

## Colors

This color system is architected to distinguish between functional states and user roles:

- **Primary (Slate Indigo):** Used for structural navigation, primary actions, and administrative headers. It evokes stability and institutional trust.
- **Success (Emerald Green):** Specifically reserved for positive feedback loops, such as "Ready for Review," "Course Completed," and achievement badges.
- **Accent (Friendly Violet):** Dedicated to student-facing touchpoints. It marks interactive learning elements, progress indicators, and "Start Lesson" buttons to provide a warmer, more encouraging atmosphere.
- **Neutral (Slate Grays):** A sophisticated range of off-whites (`#F8FAFC`) and cool grays (`#64748B`) used for dashboard backgrounds and secondary text to maintain high scannability without visual fatigue.

## Typography

The typography strategy employs two highly legible sans-serifs to distinguish between structure and content. 

**Public Sans** is used for headlines and display elements. Its slightly wider stance and institutional feel provide the "Academic" weight required for course titles and dashboard sections. 

**Inter** is the workhorse for all body copy, labels, and administrative data. It is chosen for its exceptional readability at small sizes and its neutral, systematic tone. 

- Use **Bold** weights sparingly for emphasis in data tables.
- Increase line height to `1.6` for long-form reading content in student modules to prevent eye strain.
- Labels use a medium weight (`500`) to ensure they are distinct from standard body text.

## Layout & Spacing

The system uses a **Fluid Grid** for dashboards and a **Fixed Centered Column** for learning content.

- **Admin/Review Layouts:** Utilize a 12-column grid with tight `16px` gutters. Content density is high to allow for maximum data visibility. Padding within table cells and list items is compressed (`sm` or `md`).
- **Student/Learning Layouts:** Utilize an 8-column centered grid for reading and video content. Margins are expanded to `xl` to create a "Focus Mode" that removes peripheral distractions.
- **Breakpoints:**
  - Mobile (<600px): 4 columns, `16px` margins.
  - Tablet (600px - 1024px): 8 columns, `24px` margins.
  - Desktop (>1024px): 12 columns, `48px` margins.

## Elevation & Depth

This design system uses **Tonal Layers** combined with **Ambient Shadows** to create a structured hierarchy.

- **Level 0 (Background):** Soft gray (`#F8FAFC`). Flat.
- **Level 1 (Cards/Sidebar):** Pure white background. Subtle `1px` border in `#E2E8F0`. No shadow or a very faint `2px` blur.
- **Level 2 (Active Elements/Modals):** Pure white. Medium shadow: `0 4px 12px rgba(46, 68, 130, 0.08)`. This elevation is used for course cards and active dropdowns.
- **Interaction:** On hover, interactive elements should transition from Level 1 to Level 2, signaling "clickability" through a slight lift rather than a dramatic color change.

## Shapes

The shape language is consistently **Rounded**, using an `8px` (0.5rem) base radius to soften the academic tone and make the platform feel more approachable.

- **Standard Elements:** Buttons, Input fields, and small cards use the base `8px` radius.
- **Large Containers:** Dashboard widgets and main content areas use `rounded-lg` (`16px`) to define clear boundaries.
- **Specialty Shapes:** Status chips and "Complete" indicators may use a pill-shape for maximum distinction from functional buttons.

## Components

### Buttons
- **Primary:** Solid Primary Indigo with white text. High contrast for main actions.
- **Secondary:** Transparent background with a `1px` border of Primary Indigo. 
- **Student Action:** Solid Violet for "Start Learning" or "Next Lesson."

### Input Fields
- Outlined style using `#CBD5E1` borders. On focus, the border shifts to Primary Indigo with a soft 2px outer glow. Labels are always positioned above the field for clarity.

### Cards
- **Admin Cards:** Flat with borders, high density, condensed typography.
- **Course Cards:** Elevated (Level 2), featuring a large image area, progress bar at the bottom, and generous internal padding.

### Progress Indicators
- Use the Success Emerald for completed segments and the Accent Violet for active/in-progress segments. Linear bars should have rounded caps.

### Chips & Status Tags
- **Review Required:** Soft Amber background with dark text.
- **Ready for Review:** Soft Emerald background with Emerald text.
- Tags should use `label-sm` typography and a pill shape.

### Additional Components
- **The "Focus Bar":** A sticky top-bar for students that contains only a "Back to Dashboard" link, the Course Title, and a Progress Percentage—designed to keep the user in a flow state.