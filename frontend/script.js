// ===== SISTEMA DE GERENCIAMENTO DE ESTADO =====
const CosmicState = {
    currentModule: 'dashboard',
    pomodoroState: {
        isRunning: false,
        isPaused: true,
        isFocusMode: true,
        timeLeft: 25 * 60, // 25 minutos em segundos
        totalTime: 25 * 60,
        interval: null
    }
};

// ===== INICIALIZAÇÃO DO SISTEMA =====
document.addEventListener('DOMContentLoaded', () => {
    initParticleSystem();
    setupNavigation();
    initPomodoroSystem();
    setupThemeEngine();
    
    // Mostra o módulo ativo inicial
    showModule(CosmicState.currentModule);
});

// ===== SISTEMA DE PARTÍCULAS =====
function initParticleSystem() {
    const canvas = document.getElementById('particle-canvas');
    const ctx = canvas.getContext('2d');
    
    // Configura o canvas para ocupar toda a tela
    function resizeCanvas() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    
    // Configuração das partículas
    const particles = [];
    const particleCount = window.innerWidth < 768 ? 50 : 100;
    
    // Cria partículas
    for (let i = 0; i < particleCount; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            size: Math.random() * 3 + 1,
            speedX: (Math.random() - 0.5) * 0.5,
            speedY: (Math.random() - 0.5) * 0.5,
            color: `rgba(${Math.floor(Math.random() * 100 + 155)}, 
                         ${Math.floor(Math.random() * 200 + 55)}, 
                         255, 
                         ${Math.random() * 0.5 + 0.1})`
        });
    }
    
    // Loop de animação
    function animateParticles() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        particles.forEach(particle => {
            // Atualiza posição
            particle.x += particle.speedX;
            particle.y += particle.speedY;
            
            // Mantém as partículas dentro da tela
            if (particle.x < 0 || particle.x > canvas.width) particle.speedX *= -1;
            if (particle.y < 0 || particle.y > canvas.height) particle.speedY *= -1;
            
            // Desenha a partícula
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fillStyle = particle.color;
            ctx.fill();
            
            // Efeito de brilho
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size * 2, 0, Math.PI * 2);
            ctx.fillStyle = particle.color.replace('rgba', 'rgba').replace(')', ', 0.1)');
            ctx.fill();
        });
        
        requestAnimationFrame(animateParticles);
    }
    
    animateParticles();
}

// ===== SISTEMA DE NAVEGAÇÃO =====
function setupNavigation() {
    const navPortals = document.querySelectorAll('.nav-portal');
    
    navPortals.forEach(portal => {
        portal.addEventListener('click', (e) => {
            e.preventDefault();
            const moduleId = portal.dataset.module;
            showModule(moduleId);
        });
    });
}

function showModule(moduleId) {
    // Atualiza estado
    CosmicState.currentModule = moduleId;
    
    // Atualiza navegação
    document.querySelectorAll('.nav-portal').forEach(portal => {
        portal.classList.remove('active');
        if (portal.dataset.module === moduleId) {
            portal.classList.add('active');
        }
    });
    
    // Atualiza conteúdo
    document.querySelectorAll('.content-module').forEach(module => {
        module.classList.remove('active');
        if (module.id === moduleId) {
            setTimeout(() => {
                module.classList.add('active');
            }, 50);
        }
    });
}

// ===== SISTEMA DE TEMAS =====
function setupThemeEngine() {
    // Observa mudanças no módulo ativo para atualizar o tema
    const observer = new MutationObserver(() => {
        const activeModule = document.querySelector('.content-module.active');
        if (activeModule) {
            const theme = activeModule.dataset.theme;
            updateTheme(theme);
        }
    });
    
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
}

function updateTheme(themeName) {
    const nebulaLayer = document.querySelector('.nebula-layer');
    
    switch(themeName) {
        case 'dashboard':
            nebulaLayer.style.background = 'var(--theme-dashboard)';
            break;
        case 'pomodoro':
            nebulaLayer.style.background = 'var(--theme-pomodoro)';
            break;
        case 'metas':
            nebulaLayer.style.background = 'var(--theme-metas)';
            break;
        // Adicione outros temas conforme necessário
        default:
            nebulaLayer.style.background = 'var(--theme-dashboard)';
    }
}

// ===== SISTEMA POMODORO =====
function initPomodoroSystem() {
    // Elementos DOM
    const timeDisplay = document.querySelector('.time-display');
    const statusDisplay = document.querySelector('.chrono-status');
    const startBtn = document.querySelector('.start-btn');
    const pauseBtn = document.querySelector('.pause-btn');
    const resetBtn = document.querySelector('.reset-btn');
    const skipBtn = document.querySelector('.skip-btn');
    const progressRing = document.querySelector('.ring-progress');
    
    // Configura o anel de progresso
    const radius = progressRing.r.baseVal.value;
    const circumference = radius * 2 * Math.PI;
    progressRing.style.strokeDasharray = `${circumference} ${circumference}`;
    progressRing.style.strokeDashoffset = circumference;
    
    // Atualiza o display
    updatePomodoroDisplay();
    
    // Event Listeners
    startBtn.addEventListener('click', startPomodoro);
    pauseBtn.addEventListener('click', pausePomodoro);
    resetBtn.addEventListener('click', resetPomodoro);
    skipBtn.addEventListener('click', skipPomodoro);
    
    // Funções do Pomodoro
    function startPomodoro() {
        if (CosmicState.pomodoroState.isRunning) return;
        
        CosmicState.pomodoroState.isRunning = true;
        CosmicState.pomodoroState.isPaused = false;
        
        statusDisplay.textContent = CosmicState.pomodoroState.isFocusMode 
            ? 'Foco Ativo ⚡' 
            : 'Pausa Ativa 🧘';
        
        CosmicState.pomodoroState.interval = setInterval(() => {
            if (CosmicState.pomodoroState.timeLeft <= 0) {
                completeCycle();
                return;
            }
            
            CosmicState.pomodoroState.timeLeft--;
            updatePomodoroDisplay();
            
            // Ativa efeito crítico nos últimos 60 segundos
            if (CosmicState.pomodoroState.timeLeft < 60) {
                timeDisplay.classList.add('critical');
            } else {
                timeDisplay.classList.remove('critical');
            }
        }, 1000);
    }
    
    function pausePomodoro() {
        if (!CosmicState.pomodoroState.isRunning || CosmicState.pomodoroState.isPaused) return;
        
        clearInterval(CosmicState.pomodoroState.interval);
        CosmicState.pomodoroState.isPaused = true;
        CosmicState.pomodoroState.isRunning = false;
        
        statusDisplay.textContent = CosmicState.pomodoroState.isFocusMode 
            ? 'Foco Pausado ⏸️' 
            : 'Pausa Interrompida 💤';
    }
    
    function resetPomodoro() {
        clearInterval(CosmicState.pomodoroState.interval);
        
        CosmicState.pomodoroState.isRunning = false;
        CosmicState.pomodoroState.isPaused = true;
        CosmicState.pomodoroState.isFocusMode = true;
        CosmicState.pomodoroState.timeLeft = 25 * 60;
        CosmicState.pomodoroState.totalTime = 25 * 60;
        
        statusDisplay.textContent = 'Pronto para Ativar';
        timeDisplay.classList.remove('critical');
        updatePomodoroDisplay();
    }
    
    function skipPomodoro() {
        clearInterval(CosmicState.pomodoroState.interval);
        
        CosmicState.pomodoroState.isRunning = false;
        CosmicState.pomodoroState.isPaused = true;
        
        if (CosmicState.pomodoroState.isFocusMode) {
            CosmicState.pomodoroState.isFocusMode = false;
            CosmicState.pomodoroState.timeLeft = 5 * 60;
            CosmicState.pomodoroState.totalTime = 5 * 60;
            statusDisplay.textContent = 'Pausa Forçada ⏭️';
        } else {
            CosmicState.pomodoroState.isFocusMode = true;
            CosmicState.pomodoroState.timeLeft = 25 * 60;
            CosmicState.pomodoroState.totalTime = 25 * 60;
            statusDisplay.textContent = 'Retomando Foco 🚀';
        }
        
        timeDisplay.classList.remove('critical');
        updatePomodoroDisplay();
    }
    
    function completeCycle() {
        clearInterval(CosmicState.pomodoroState.interval);
        
        // Toca o som de alerta
        const alertSound = document.getElementById('alert-sound');
        alertSound.play().catch(e => console.error("Erro ao tocar áudio:", e));
        
        if (CosmicState.pomodoroState.isFocusMode) {
            // Terminou o tempo de foco, inicia pausa curta
            CosmicState.pomodoroState.isFocusMode = false;
            CosmicState.pomodoroState.timeLeft = 5 * 60;
            CosmicState.pomodoroState.totalTime = 5 * 60;
            statusDisplay.textContent = 'Pausa Iniciada 🎉';
        } else {
            // Terminou a pausa, reinicia o foco
            CosmicState.pomodoroState.isFocusMode = true;
            CosmicState.pomodoroState.timeLeft = 25 * 60;
            CosmicState.pomodoroState.totalTime = 25 * 60;
            statusDisplay.textContent = 'Foco Reiniciado 🚀';
        }
        
        CosmicState.pomodoroState.isRunning = false;
        CosmicState.pomodoroState.isPaused = true;
        timeDisplay.classList.remove('critical');
        updatePomodoroDisplay();
        
        // Reinicia automaticamente após 2 segundos
        setTimeout(startPomodoro, 2000);
    }
    
    function updatePomodoroDisplay() {
        const minutes = Math.floor(CosmicState.pomodoroState.timeLeft / 60);
        const seconds = CosmicState.pomodoroState.timeLeft % 60;
        timeDisplay.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        
        // Atualiza o anel de progresso
        const offset = circumference - (CosmicState.pomodoroState.timeLeft / CosmicState.pomodoroState.totalTime) * circumference;
        progressRing.style.strokeDashoffset = offset;
    }
}
