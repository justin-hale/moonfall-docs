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
.github/workflows/
├── deploy.yml                  # Manual site deployment
└── generate-session.yml        # Automated session generation + deploy

docs/
├── intro.md                    # Homepage content
├── player-characters/          # Character profiles
│   ├── _category_.json
│   ├── bru.md
│   ├── elspeth.md
│   └── ...
├── sessions/                   # Session summaries (generated or manual)
│   ├── _category_.json
│   ├── session-1.md
│   ├── session-42.md
│   ├── interlude-1.md
│   └── ...
└── transcripts/                # Cleaned transcripts (generated from SRT)

transcripts_raw/                # Drop .srt files here to trigger automation

src/
├── components/                 # React components
├── css/                       # Custom styles
└── data/                      # Generated data files

scripts/
├── automate_session.py        # Session generation automation script
├── add-session-positions.js   # Updates sidebar positions
└── generate-sessions-data.js  # Generates session lists

static/
├── img/                       # Images and assets
└── CNAME                      # Custom domain configuration
```

## 🤖 Automated Session Generation

The fastest way to create session notes is to let the automation handle everything. Just upload a transcript and push to `main`.

### How to Generate a New Session

1. **Get your `.srt` transcript file** from the recording
2. **Add it to the `transcripts_raw/` directory**:
   ```bash
   cp ~/Downloads/my-session-recording.srt transcripts_raw/
   ```
3. **Commit and push to `main`** (or open a PR and merge it):
   ```bash
   git add transcripts_raw/
   git commit -m "Add transcript for session 42"
   git push origin main
   ```
4. **The GitHub Actions workflow will automatically**:
   - Clean and process the transcript
   - Invoke Claude to generate full session notes matching the style of previous sessions
   - Commit the generated files back to the repo
   - Build and deploy the updated site to GitHub Pages

5. **Monitor progress** in the repository's **Actions** tab — you'll see real-time streaming output from Claude as it works

### Manual Trigger

You can also trigger session generation manually from the **Actions** tab:

1. Go to **Actions** > **Generate Session Notes**
2. Click **Run workflow**
3. Optionally specify a session number or mark it as an interlude
4. Click **Run workflow** to start

### Running Locally

```bash
# Full automation (clean transcript + generate notes)
python scripts/automate_session.py

# Skip transcript cleaning (use existing transcript in docs/transcripts/)
python scripts/automate_session.py --no-clean

# Specify session number or create an interlude
python scripts/automate_session.py --session-number 42
python scripts/automate_session.py --interlude

# Just prepare the prompt without invoking Claude
python scripts/automate_session.py --no-claude
```

### Required Setup

- **Repository secret**: `ANTHROPIC_API_KEY` must be set in **Settings > Secrets and variables > Actions** for the GitHub Actions workflow to work
- **Locally**: Either set the `ANTHROPIC_API_KEY` environment variable or log in with `claude login`

---

## ✍️ Creating Session Files Manually

If you prefer to write session notes by hand instead of using the automation:

### Session File Template

```markdown
---
title: "36: Session Title Here"
date: 2025-10-10
description: "Brief description of what happens in this session."
summary: "Same as description, used for metadata."
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
| `podcastlink` | ✅ | URL to podcast episode |
| `sidebar_position` | 🔄 | Auto-generated, don't set manually |

**Legend**: ✅ Required, ⚠️ Optional but recommended, 🔄 Auto-managed

### File Naming Convention

- **Sessions**: `session-{number}.md` (e.g., `session-36.md`)
- **Interludes**: `interlude-{number}.md` (e.g., `interlude-11.md`)

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

The site deploys to [moonfallsessions.com](https://moonfallsessions.com) via GitHub Actions.

### Automated (via Session Generation)

When the **Generate Session Notes** workflow runs (triggered by pushing an `.srt` file or manually), it automatically builds and deploys the site after generating the session notes. No extra steps needed.

### Manual Deployment

To deploy without generating session notes (e.g., after manual edits):

1. Go to **Actions** > **Deploy to GitHub Pages**
2. Click **Run workflow** > **Run workflow**

Or deploy locally:

```bash
npm run build
npm run deploy
```

### Custom Domain Configuration

The site is configured for `moonfallsessions.com`:
- **CNAME file**: `static/CNAME` contains the domain
- **DNS Settings**: Domain points to GitHub Pages IPs
- **HTTPS**: Automatically enabled by GitHub Pages

## 🎨 Customization

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
