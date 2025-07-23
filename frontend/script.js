// frontend/script.js

document.addEventListener('DOMContentLoaded', () => {
    const navLinks = document.querySelectorAll('.main-nav a');
    const contentSections = document.querySelectorAll('.content-section');
    const mainContent = document.querySelector('.main-content'); // Get the main-content element

    // Function to show the correct section and apply the theme
    const showSection = (sectionId) => {
        contentSections.forEach(section => {
            if (section.id === sectionId) {
                section.classList.remove('hidden');
                section.classList.add('active'); // Optional, to indicate which section is active visually
            } else {
                section.classList.add('hidden');
                section.classList.remove('active');
            }
        });

        // Update 'active' class on navigation links
        navLinks.forEach(link => {
            if (link.dataset.section === sectionId) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });

        // --- NEW: Change the theme of the main-content ---
        // Remove all existing theme classes
        mainContent.classList.forEach(cls => {
            if (cls.startsWith('theme-')) {
                mainContent.classList.remove(cls);
            }
        });
        // Add the new theme class based on the section ID
        mainContent.classList.add(`theme-${sectionId}`);
        // --- END OF NEW ---
    };

    // Add click event listener to navigation links
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault(); // Prevent default link behavior
            const sectionId = e.target.dataset.section;
            showSection(sectionId);
        });
    });

    // Show the Dashboard section by default when the page loads
    showSection('dashboard');
});

// Future Pomodoro, Goals, etc. logic will go here
