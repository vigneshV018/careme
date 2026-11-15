// CareMe Client Scripts & PWA Infrastructure

// -----------------------------------------------------------------------------
// CSRF Protection Helper & Fetch Interceptor
// -----------------------------------------------------------------------------
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const match = document.cookie.match(/careme_csrf=([^;]+)/);
    return match ? match[1] : '';
}

// Automatically attach X-CSRF-Token header to all mutating AJAX requests
const originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
        options.headers = options.headers || {};
        const token = getCsrfToken();
        if (token) {
            if (options.headers instanceof Headers) {
                if (!options.headers.has('X-CSRF-Token')) {
                    options.headers.set('X-CSRF-Token', token);
                }
            } else if (Array.isArray(options.headers)) {
                options.headers.push(['X-CSRF-Token', token]);
            } else {
                if (!options.headers['X-CSRF-Token']) {
                    options.headers['X-CSRF-Token'] = token;
                }
            }
        }
    }
    return originalFetch(url, options);
};

// Automatically ensure every POST form in DOM carries the CSRF token
document.addEventListener("DOMContentLoaded", () => {
    const token = getCsrfToken();
    if (token) {
        document.querySelectorAll("form").forEach(form => {
            if ((form.method || "").toUpperCase() === "POST") {
                if (!form.querySelector('input[name="csrf_token"]')) {
                    const input = document.createElement("input");
                    input.type = "hidden";
                    input.name = "csrf_token";
                    input.value = token;
                    form.appendChild(input);
                }
            }
        });
    }
});

// -----------------------------------------------------------------------------
// PWA Service Worker & Add to Home Screen
// -----------------------------------------------------------------------------
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/service-worker.js')
            .then(reg => {
                // Registered successfully
            })
            .catch(err => {
                console.log('Service Worker registration skipped:', err);
            });
    });
}

let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    const banner = document.getElementById('pwa-install-banner');
    if (banner) {
        banner.classList.remove('hidden');
    }
});

function triggerPwaInstall() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(() => {
            deferredPrompt = null;
            const banner = document.getElementById('pwa-install-banner');
            if (banner) banner.classList.add('hidden');
        });
    }
}

function dismissPwaInstall() {
    const banner = document.getElementById('pwa-install-banner');
    if (banner) banner.classList.add('hidden');
}

// -----------------------------------------------------------------------------
// Mobile Hamburger Menu Navigation
// -----------------------------------------------------------------------------
function toggleMobileMenu() {
    const drawer = document.getElementById('mobile-menu-drawer');
    if (drawer) {
        drawer.classList.toggle('hidden');
    }
}

// -----------------------------------------------------------------------------
// Web Speech API for Elder Mode
// -----------------------------------------------------------------------------
function speakRoutine(text) {
    if (!('speechSynthesis' in window)) {
        alert("Text to speech is not supported in this browser.");
        return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    utterance.lang = 'en-IN'; // Indian English cadence
    window.speechSynthesis.speak(utterance);
}

// -----------------------------------------------------------------------------
// Siren Sound Generator (Web Audio API)
// -----------------------------------------------------------------------------
function playAlarmSound() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        let osc = audioCtx.createOscillator();
        let gain = audioCtx.createGain();
        osc.type = 'sawtooth';

        let now = audioCtx.currentTime;
        osc.frequency.setValueAtTime(440, now);
        osc.frequency.exponentialRampToValueAtTime(880, now + 0.3);
        osc.frequency.exponentialRampToValueAtTime(440, now + 0.6);
        osc.frequency.exponentialRampToValueAtTime(880, now + 0.9);
        osc.frequency.exponentialRampToValueAtTime(440, now + 1.2);

        gain.gain.setValueAtTime(0.3, now);
        gain.gain.exponentialRampToValueAtTime(0.01, now + 1.4);

        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start(now);
        osc.stop(now + 1.4);
    } catch (e) {
        console.warn("Audio Context not allowed without user interaction", e);
    }
}

// -----------------------------------------------------------------------------
// Geolocation & Emergency SOS
// -----------------------------------------------------------------------------
function triggerEmergencySOS(buttonElement) {
    if (!confirm("Are you sure you want to trigger an EMERGENCY SOS? This will immediately alert all family members and caregivers!")) {
        return;
    }

    playAlarmSound();

    let lat = 11.0168; // Default Coimbatore
    let lng = 76.9558;

    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                lat = pos.coords.latitude;
                lng = pos.coords.longitude;
                submitSOSForm(lat, lng);
            },
            (err) => {
                console.log("Using default location", err);
                submitSOSForm(lat, lng);
            },
            { timeout: 4000 }
        );
    } else {
        submitSOSForm(lat, lng);
    }
}

function submitSOSForm(lat, lng) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = "/alerts/sos";

    const csrfToken = getCsrfToken();
    if (csrfToken) {
        const csrfInput = document.createElement("input");
        csrfInput.type = "hidden";
        csrfInput.name = "csrf_token";
        csrfInput.value = csrfToken;
        form.appendChild(csrfInput);
    }

    const latInput = document.createElement("input");
    latInput.type = "hidden";
    latInput.name = "lat";
    latInput.value = lat;
    form.appendChild(latInput);

    const lngInput = document.createElement("input");
    lngInput.type = "hidden";
    lngInput.name = "lng";
    lngInput.value = lng;
    form.appendChild(lngInput);

    const redirectInput = document.createElement("input");
    redirectInput.type = "hidden";
    redirectInput.name = "redirect_to";
    redirectInput.value = window.location.pathname;
    form.appendChild(redirectInput);

    document.body.appendChild(form);
    form.submit();
}

// -----------------------------------------------------------------------------
// Clipboard Helper
// -----------------------------------------------------------------------------
function copyText(text, btnElement) {
    navigator.clipboard.writeText(text).then(() => {
        const original = btnElement.innerHTML;
        btnElement.innerHTML = `<i class="fa-solid fa-check text-emerald-500"></i> Copied!`;
        setTimeout(() => {
            btnElement.innerHTML = original;
        }, 2000);
    });
}
