const fs = require('fs');
const path = require('path');

// Script to add position frontmatter to session files for reverse ordering
function addPositionFrontmatter() {
  const sessionsDir = path.join(__dirname, '..', 'docs', 'sessions');
  
  try {
    const files = fs.readdirSync(sessionsDir);
    
    // Filter for session and interlude files
    const sessionFiles = files.filter(file => 
      file.match(/^session-\d+\.md$/)
    );
    const interludeFiles = files.filter(file => 
      file.match(/^interlude-\d+\.md$/)
    );
    
    console.log(`Processing ${sessionFiles.length} sessions and ${interludeFiles.length} interludes...`);
    
    // Combine all files and extract their dates for chronological sorting
    const allFiles = [...sessionFiles, ...interludeFiles];
    const filesWithDates = [];
    
    allFiles.forEach(file => {
      const filePath = path.join(sessionsDir, file);
      try {
        const content = fs.readFileSync(filePath, 'utf-8');
        
        // Extract date from frontmatter
        const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
        if (frontmatterMatch) {
          const frontmatter = frontmatterMatch[1];
          const dateMatch = frontmatter.match(/date:\s*(.+)/);
          if (dateMatch) {
            const dateStr = dateMatch[1].trim().replace(/['"]/g, '');
            const date = new Date(dateStr);
            filesWithDates.push({ file, date, dateStr });
          } else {
            console.warn(`No date found in ${file}, skipping...`);
          }
        } else {
          console.warn(`No frontmatter found in ${file}, skipping...`);
        }
      } catch (error) {
        console.error(`Error reading ${file}:`, error);
      }
    });
    
    // Sort by date in descending order (newest first)
    const sortedFiles = filesWithDates.sort((a, b) => b.date - a.date);
    
    console.log('Chronological order (newest first):');
    sortedFiles.forEach((item, index) => {
      console.log(`${index + 1}. ${item.file} (${item.dateStr})`);
    });
    
    // Assign positions starting from 1
    sortedFiles.forEach(({ file }, index) => {
      const position = index + 1;
      addPositionToFile(path.join(sessionsDir, file), position);
    });
    
    console.log('Successfully added position frontmatter to all session files!');
    
  } catch (error) {
    console.error('Error processing session files:', error);
  }
}

function addPositionToFile(filePath, position) {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    
    // Check if file already has frontmatter
    if (content.startsWith('---')) {
      // File has frontmatter, check if it already has position
      const frontmatterEnd = content.indexOf('---', 3);
      const frontmatter = content.substring(0, frontmatterEnd + 3);
      const body = content.substring(frontmatterEnd + 3);
      
      if (frontmatter.includes('sidebar_position:')) {
        // Update existing position
        const updatedFrontmatter = frontmatter.replace(
          /sidebar_position:\s*\d+/,
          `sidebar_position: ${position}`
        );
        fs.writeFileSync(filePath, updatedFrontmatter + body);
      } else {
        // Add position to existing frontmatter
        const updatedFrontmatter = frontmatter.replace(
          /---$/,
          `sidebar_position: ${position}\n---`
        );
        fs.writeFileSync(filePath, updatedFrontmatter + body);
      }
    } else {
      // File has no frontmatter, add it
      const newContent = `---\nsidebar_position: ${position}\n---\n\n${content}`;
      fs.writeFileSync(filePath, newContent);
    }
    
  } catch (error) {
    console.error(`Error processing file ${filePath}:`, error);
  }
}

// Run the script
addPositionFrontmatter();