# Moonfall Sessions Documentation

A [Docusaurus](https://docusaurus.io/) site for documenting D&D campaign sessions, featuring automatic chronological ordering and GitHub Pages deployment.

## 🚀 Quick Start

```bash
# Install dependencies
npm install

# Start development server
npm start

# Build for production
npm run build

# Serve built site locally
npm run serve
```

## 📁 Project Structure

```
docs/
├── intro.md                    # Homepage content
├── player-characters/          # Character profiles
│   ├── _category_.json
│   ├── bru.md
│   ├── elspeth.md
│   └── ...
└── sessions/                   # Session summaries
    ├── _category_.json
    ├── session-1.md
    ├── session-36.md
    ├── interlude-1.md
    └── interlude-11.md

src/
├── components/                 # React components
├── css/                       # Custom styles
└── data/                      # Generated data files

scripts/
├── add-session-positions.js   # Updates sidebar positions
└── generate-sessions-data.js  # Generates session lists

static/
├── img/                       # Images and assets
└── CNAME                      # Custom domain configuration
```

## ✍️ Creating New Session Files

### Session File Template

Create new session files following this template structure:

```markdown
---
title: "36: Session Title Here"
date: 2025-10-10
description: "Brief description of what happens in this session."
summary: "Same as description, used for metadata."
featureimage: "C4E36.webp"
image: "/img/C4E36.webp"
podcastlink: "https://your-podcast-link-here"
sidebar_position: 1
---

**[🎧 Podcast Link](https://your-podcast-link-here) • *October 10, 2025***

## Session Summary

Write your session summary here...

### Key Events
- Important event 1
- Important event 2
- Important event 3

### Character Moments
- Character development or important roleplay moments

### Combat Encounters
- Notable fights or encounters

### Story Progression
- How the story advanced this session
```

### Interlude File Template

```markdown
---
title: "Interlude XI: Interlude Title Here"
date: 2025-05-30
description: "Brief description of the interlude content."
summary: "Same as description."
featureimage: "C4I11.webp"
podcastlink: "https://your-podcast-link-here"
sidebar_position: 16
---

**[🎧 Podcast Link](https://your-podcast-link-here) • *May 30, 2025***

Write your interlude content here...
```

### Frontmatter Fields Explained

| Field | Required | Description |
|-------|----------|-------------|
| `title` | ✅ | Display title (format: "Number: Title") |
| `date` | ✅ | Publication date (YYYY-MM-DD) - used for chronological sorting |
| `description` | ✅ | Brief summary for SEO and previews |
| `summary` | ✅ | Usually same as description |
| `featureimage` | ⚠️ | Filename of feature image |
| `image` | ⚠️ | Full path to image (`/img/filename.webp`) |
| `podcastlink` | ✅ | URL to podcast episode |
| `sidebar_position` | 🔄 | Auto-generated, don't set manually |

**Legend**: ✅ Required, ⚠️ Optional but recommended, 🔄 Auto-managed

### File Naming Convention

- **Sessions**: `session-{number}.md` (e.g., `session-36.md`)
- **Interludes**: `interlude-{number}.md` (e.g., `interlude-11.md`)
- **Images**: `C4E{number}.webp` for sessions, `C4I{number}.webp` for interludes

## 🔄 Updating Sidebar Positions

The sidebar is automatically ordered chronologically (newest first) based on the `date` field in each file's frontmatter.

### After Adding New Content

1. **Create your new session/interlude file** with the correct `date` in frontmatter
2. **Update positions**: 
   ```bash
   npm run update-positions
   ```
3. **Verify the order** by starting the dev server:
   ```bash
   npm start
   ```

### How Position Ordering Works

- Files are sorted by `date` field (newest first)
- Position numbers start at 1 and increment
- Sessions and interludes are mixed chronologically
- Example order:
  - Session 36 (2025-10-10) → `sidebar_position: 1`
  - Session 35 (2025-10-03) → `sidebar_position: 2`
  - Interlude 11 (2025-05-30) → `sidebar_position: 16`

## 🏗️ Building and Testing

### Development

```bash
# Start development server (with hot reload)
npm start

# Generate fresh session data
npm run generate-sessions

# Update sidebar positions
npm run update-positions
```

### Production Build

```bash
# Build for production (includes session data generation)
npm run build

# Test the built site locally
npm run serve
```

### Available Scripts

| Script | Command | Description |
|--------|---------|-------------|
| Development | `npm start` | Start dev server at http://localhost:3000 |
| Build | `npm run build` | Build for production (auto-generates session data) |
| Serve | `npm run serve` | Serve built site locally |
| Update Positions | `npm run update-positions` | Reorder sidebar based on dates |
| Generate Sessions | `npm run generate-sessions` | Regenerate session list data |
| Type Check | `npm run typecheck` | Run TypeScript checks |

## 🚀 Deployment to GitHub Pages

The site automatically deploys to [moonfallsessions.com](https://moonfallsessions.com) via GitHub Actions.

### Automatic Deployment

Every push to the `main` branch triggers automatic deployment:

1. **Commit and push your changes**:
   ```bash
   git add .
   git commit -m "Add Session 37"
   git push origin main
   ```

2. **GitHub Actions will**:
   - Install dependencies
   - Run the build process (including session data generation)
   - Deploy to GitHub Pages
   - Update your live site

3. **Check deployment status**:
   - Go to your repository → Actions tab
   - Monitor the deployment progress
   - Site updates in ~2-3 minutes

### Manual Deployment

If needed, you can deploy manually:

```bash
# Build and deploy
npm run build
npm run deploy
```

### Custom Domain Configuration

The site is configured for `moonfallsessions.com`:
- **CNAME file**: `static/CNAME` contains the domain
- **DNS Settings**: Domain points to GitHub Pages IPs
- **HTTPS**: Automatically enabled by GitHub Pages

## 🎨 Customization

### Adding Images

1. **Place images** in `static/img/`
2. **Reference in markdown**: `/img/filename.webp`
3. **Use in frontmatter**: 
   ```yaml
   featureimage: "filename.webp"
   image: "/img/filename.webp"
   ```

### Styling

- **Main styles**: `src/css/custom.css`
- **Component styles**: Individual component directories
- **Dark mode**: Automatically supported

### Navigation

- **Navbar**: Configure in `docusaurus.config.ts`
- **Sidebar**: Auto-generated from file structure and positions
- **Footer**: Customize in theme configuration

## 🛠️ Troubleshooting

### Common Issues

**Sidebar order is wrong**
```bash
npm run update-positions
```

**Images not showing**
- Check file path: `/img/filename.webp`
- Ensure image is in `static/img/`
- Verify filename matches exactly

**Build fails**
- Check for missing frontmatter fields
- Verify all markdown syntax
- Run `npm run typecheck`

**Deployment issues**
- Check GitHub Actions logs
- Verify repository settings → Pages configuration
- Ensure custom domain DNS is correct

### Getting Help

1. **Check the console** for error messages
2. **Review GitHub Actions logs** for deployment issues  
3. **Verify file structure** matches expected format
4. **Test locally** before pushing to main

## 📋 Content Guidelines

### Writing Style
- Use clear, descriptive titles
- Include session dates in podcast links
- Write engaging summaries for better SEO
- Use consistent formatting for character names

### Image Guidelines
- **Format**: WebP preferred for smaller file sizes
- **Naming**: Follow `C4E{number}.webp` or `C4I{number}.webp` pattern
- **Size**: Optimize for web (aim for <500KB)
- **Alt text**: Will be auto-generated from title

### SEO Best Practices
- Include descriptive `description` fields
- Use relevant keywords in titles and summaries
- Ensure all podcast links are working
- Add proper dates for chronological organization

---

## 🔧 Technical Details

- **Framework**: Docusaurus v3.9.2
- **Node.js**: v18+ required
- **Deployment**: GitHub Actions → GitHub Pages
- **Domain**: moonfallsessions.com
- **CDN**: GitHub's global CDN

Built with ❤️ for the Moonfall D&D campaign.
