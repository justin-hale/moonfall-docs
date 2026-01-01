const fs = require('fs');
const path = require('path');
const matter = require('gray-matter');

// Plugin to sort sessions by date in descending order (newest first)
function sortSessionsByDatePlugin(context, options) {
  return {
    name: 'sort-sessions-by-date-plugin',
    
    async contentLoaded({content, actions}) {
      // This plugin modifies the sidebar item order
    },
    
    // Hook into the docs plugin to modify sidebar generation
    configureWebpack(config, isServer, utils) {
      return {};
    },
  };
}

// Custom sidebar item sorter function
function sortSessionsByDate(items) {
  const sessionsDir = path.join(__dirname, '..', 'docs', 'sessions');
  
  // Read all markdown files and extract their dates
  const sessionDates = {};
  
  try {
    const files = fs.readdirSync(sessionsDir);
    
    files.forEach(file => {
      if (file.endsWith('.md')) {
        const filePath = path.join(sessionsDir, file);
        const content = fs.readFileSync(filePath, 'utf8');
        const { data } = matter(content);
        
        if (data.date) {
          const docId = file.replace('.md', '');
          sessionDates[docId] = new Date(data.date);
        }
      }
    });
  } catch (error) {
    console.error('Error reading session dates:', error);
  }
  
  // Sort items by date (newest first)
  return items.sort((a, b) => {
    const aDate = sessionDates[a.id] || new Date(0);
    const bDate = sessionDates[b.id] || new Date(0);
    return bDate - aDate; // Descending order
  });
}

module.exports = sortSessionsByDatePlugin;
module.exports.sortSessionsByDate = sortSessionsByDate;
