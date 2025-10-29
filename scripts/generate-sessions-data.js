const fs = require('fs');
const path = require('path');

// Script to generate sessions data at build time
function generateSessionsData() {
  const sessionsDir = path.join(__dirname, '..', 'docs', 'sessions');
  const outputPath = path.join(__dirname, '..', 'src', 'data', 'sessions.json');
  
  try {
    const files = fs.readdirSync(sessionsDir);
    
    // Filter for session and interlude files
    const sessionFiles = files.filter(file => 
      file.match(/^session-\d+\.md$/) && file !== 'index.md'
    );
    const interludeFiles = files.filter(file => 
      file.match(/^interlude-\d+\.md$/)
    );
    
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
    
    // Create output directory if it doesn't exist
    const outputDir = path.dirname(outputPath);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    
    // Write the data to a JSON file
    const data = { sessions, interludes };
    fs.writeFileSync(outputPath, JSON.stringify(data, null, 2));
    
    console.log(`Generated sessions data: ${sessions.length} sessions, ${interludes.length} interludes`);
    
  } catch (error) {
    console.error('Error generating sessions data:', error);
  }
}

// Run the script
generateSessionsData();