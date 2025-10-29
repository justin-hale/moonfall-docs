const fs = require('fs');
const path = require('path');

// Plugin to generate sessions data at build time
function sessionsDataPlugin(context, options) {
  return {
    name: 'sessions-data-plugin',
    
    async loadContent() {
      const sessionsDir = path.join(context.siteDir, 'docs', 'sessions');
      console.log('Loading sessions from:', sessionsDir);
      
      try {
        const files = fs.readdirSync(sessionsDir);
        console.log('Found files:', files);
        
        // Filter for session and interlude files
        const sessionFiles = files.filter(file => 
          file.match(/^session-\d+\.md$/) && file !== 'index.md'
        );
        const interludeFiles = files.filter(file => 
          file.match(/^interlude-\d+\.md$/)
        );
        
        console.log('Session files:', sessionFiles);
        console.log('Interlude files:', interludeFiles);
        
        // Extract numbers and sort
        const sessions = sessionFiles
          .map(file => {
            const match = file.match(/session-(\d+)\.md/);
            return match ? {
              number: parseInt(match[1], 10),
              title: `Session ${match[1]}`,
              href: `/sessions/session-${match[1]}`,
              id: `session-${match[1]}`
            } : null;
          })
          .filter(Boolean)
          .sort((a, b) => b.number - a.number); // Newest first
        
        const interludes = interludeFiles
          .map(file => {
            const match = file.match(/interlude-(\d+)\.md/);
            return match ? {
              number: parseInt(match[1], 10),
              title: `Interlude ${match[1]}`,
              href: `/sessions/interlude-${match[1]}`,
              id: `interlude-${match[1]}`
            } : null;
          })
          .filter(Boolean)
          .sort((a, b) => b.number - a.number); // Newest first
        
        console.log('Generated sessions:', sessions.slice(0, 3));
        console.log('Generated interludes:', interludes.slice(0, 3));
        
        return { sessions, interludes };
      } catch (error) {
        console.error('Error reading sessions directory:', error);
        return { sessions: [], interludes: [] };
      }
    },
    
    async contentLoaded({content, actions}) {
      const {setGlobalData} = actions;
      console.log('Setting global data:', content);
      setGlobalData(content);
    },
  };
}

module.exports = sessionsDataPlugin;