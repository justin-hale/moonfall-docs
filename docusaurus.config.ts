import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Moonfall Sessions',
  tagline: 'A D&D Campaign Documentation',
  favicon: 'img/favicon.ico',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  // Set the production url of your site here
  url: 'https://moonfallsessions.com',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For custom domains, use '/'
  baseUrl: '/',

  // Ensure trailing slashes for consistent URLs
  trailingSlash: true,

  // GitHub pages deployment config.
  organizationName: 'justin-hale', // Your GitHub username
  projectName: 'moonfall-docs', // Your repo name

  onBrokenLinks: 'throw',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/justin-hale/moonfall-docs/tree/main/',
          // Make PodcastLink component available globally in MDX
          remarkPlugins: [],
          rehypePlugins: [],
          // Make the sessions page the homepage
          routeBasePath: '/',
        },
        blog: false, // Disable blog
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // Algolia Search Configuration
    algolia: {
      appId: 'N7HDFLOV04',
      apiKey: '8ff99d380d018501b49942734aaed14a',
      indexName: 'moonfallsessions',
      contextualSearch: false,
      searchParameters: {
        facetFilters: [],
      },
    },
    // Default social card for pages without specific images - using Session 1 podcast background
    image: 'img/moonfall-social-card.jpg',
    
    // Enhanced metadata for better SEO and social sharing
    metadata: [
      {name: 'keywords', content: 'D&D, dungeons and dragons, campaign, moonfall, sessions, podcast'},
      {name: 'twitter:card', content: 'summary_large_image'},
      {property: 'og:type', content: 'website'},
      {property: 'og:updated_time', content: new Date().toISOString()},
      {name: 'cache-control', content: 'no-cache, no-store, must-revalidate'},
      {name: 'algolia-site-verification', content: '39B38526BA0E37E0'},
    ],
    
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Moonfall Sessions',
      logo: {
        alt: 'Moonfall Sessions Logo',
        src: 'img/favicon.svg',
      },
      items: [
        {
          href: 'https://creators.spotify.com/pod/profile/topher-hooper/episodes/',
          label: 'Podcasts',
          position: 'right',
        },
      ],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
