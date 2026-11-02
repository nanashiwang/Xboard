({
  name: 'VueTurnstile',
  emits: ['update:modelValue', 'error', 'unsupported', 'expired', 'before-interactive', 'after-interactive'],
  props: {
    siteKey: { type: String, required: true }, modelValue: { type: String, required: true },
    resetInterval: { type: Number, default: 295000 }, size: { type: String, default: 'normal' },
    theme: { type: String, default: 'auto' }, language: { type: String, default: 'auto' },
    action: { type: String, default: 'passport' }, appearance: { type: String, default: 'always' },
    renderOnMount: { type: Boolean, default: true }
  },
  data: () => ({ resetTimeout: undefined, widgetId: undefined, active: false, loading: false }),
  computed: {
    turnstileOptions() {
      return {
        sitekey: this.siteKey, theme: this.theme, language: this.language, size: this.size,
        action: this.action, appearance: this.appearance, retry: 'never', 'refresh-expired': 'manual',
        callback: this.callback, 'error-callback': this.errorCallback,
        'expired-callback': this.expiredCallback, 'unsupported-callback': this.unsupportedCallback,
        'before-interactive-callback': this.beforeInteractiveCallback,
        'after-interactive-callback': this.afterInteractivecallback
      };
    }
  },
  methods: {
    afterInteractivecallback() { this.$emit('after-interactive'); },
    beforeInteractiveCallback() { this.$emit('before-interactive'); },
    expiredCallback() { this.$emit('update:modelValue', ''); this.$emit('expired'); },
    unsupportedCallback() { this.errorCallback('unsupported'); },
    errorCallback(code) {
      clearTimeout(this.resetTimeout);
      this.$emit('update:modelValue', ''); this.$emit('error', code);
      return true;
    },
    callback(token) {
      this.$emit('update:modelValue', token);
      clearTimeout(this.resetTimeout);
      this.resetTimeout = setTimeout(() => this.expiredCallback(), this.resetInterval);
    },
    reset() {
      clearTimeout(this.resetTimeout); this.$emit('update:modelValue', '');
      if (window.turnstile && this.widgetId !== undefined) window.turnstile.reset(this.widgetId);
      else this.load();
    },
    remove() {
      if (window.turnstile && this.widgetId !== undefined) window.turnstile.remove(this.widgetId);
      this.widgetId = undefined;
    },
    render() { this.widgetId = window.turnstile.render(this.$refs.turnstile, this.turnstileOptions); },
    async load() {
      if (this.loading) return;
      this.loading = true;
      try {
        if (!window.turnstile) {
          if (!GY) {
            GY = new Promise((resolve, reject) => {
              const script = document.createElement('script');
              let done = false;
              const finish = (failed) => {
                if (done) return;
                done = true; clearTimeout(timer);
                if (failed) { GY = undefined; script.remove(); reject(new Error('Turnstile unavailable')); }
                else resolve();
              };
              const timer = setTimeout(() => finish(true), 15000);
              window[KY] = () => finish(false);
              script.src = `https://challenges.cloudflare.com/turnstile/v0/api.js?onload=${KY}&render=explicit`;
              script.async = true; script.onerror = () => finish(true);
              document.head.appendChild(script);
            });
          }
          await GY;
        }
        if (this.active && this.widgetId === undefined) this.render();
      } catch (_) {
        if (this.active) this.errorCallback('load_failed');
      } finally { this.loading = false; }
    }
  },
  mounted() { this.active = true; if (this.renderOnMount) this.load(); },
  beforeUnmount() { this.active = false; clearTimeout(this.resetTimeout); this.remove(); }
})
