/**
 * DeviceService - Kapselt App-Lifecycle, StatusBar, Safe-Areas und Screen-Orientation.
 */

export interface SafeAreaInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export type AppStateListener = (isActive: boolean) => void;

export class DeviceService {
  private static instance: DeviceService;
  private appStateListeners: AppStateListener[] = [];
  private safeAreaInsets: SafeAreaInsets = { top: 0, right: 0, bottom: 0, left: 0 };

  private constructor() {
    this.initDeviceSettings();
    this.setupLifecycleListeners();
    this.calculateSafeAreaInsets();
  }

  public static getInstance(): DeviceService {
    if (!DeviceService.instance) {
      DeviceService.instance = new DeviceService();
    }
    return DeviceService.instance;
  }

  private async initDeviceSettings(): Promise<void> {
    // StatusBar Setup
    try {
      const { StatusBar, Style } = await import('@capacitor/status-bar');
      await StatusBar.setStyle({ style: Style.Dark });
      await StatusBar.setOverlaysWebView({ overlay: true });
    } catch {
      // Web Fallback
    }

    // Screen Orientation Lock auf Portrait
    try {
      const { ScreenOrientation } = await import('@capacitor/screen-orientation');
      await ScreenOrientation.lock({ orientation: 'portrait' });
    } catch {
      // Web Fallback oder nicht unterstützt
    }
  }

  private async setupLifecycleListeners(): Promise<void> {
    try {
      const { App } = await import('@capacitor/app');
      App.addListener('appStateChange', (state) => {
        this.notifyAppStateChange(state.isActive);
      });
    } catch {
      // Browser visibility change Fallback
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', () => {
          const isActive = document.visibilityState === 'visible';
          this.notifyAppStateChange(isActive);
        });
      }
    }
  }

  public addAppStateListener(listener: AppStateListener): () => void {
    this.appStateListeners.push(listener);
    return () => {
      this.appStateListeners = this.appStateListeners.filter((l) => l !== listener);
    };
  }

  private notifyAppStateChange(isActive: boolean): void {
    for (const listener of this.appStateListeners) {
      listener(isActive);
    }
  }

  /**
   * Berechnet Safe Area Insets dynamisch aus CSS Custom Properties oder Fallbacks
   */
  public calculateSafeAreaInsets(): SafeAreaInsets {
    if (typeof window === 'undefined' || typeof document === 'undefined') {
      return this.safeAreaInsets;
    }

    const computedStyle = getComputedStyle(document.documentElement);
    const parseInset = (propName: string, fallback: number = 0): number => {
      const val = computedStyle.getPropertyValue(propName).trim();
      const parsed = parseFloat(val);
      return isNaN(parsed) ? fallback : parsed;
    };

    this.safeAreaInsets = {
      top: parseInset('--sat', 0),
      right: parseInset('--sar', 0),
      bottom: parseInset('--sab', 0),
      left: parseInset('--sal', 0)
    };

    return this.safeAreaInsets;
  }

  public getSafeArea(): SafeAreaInsets {
    return this.safeAreaInsets;
  }
}

export const deviceService = DeviceService.getInstance();
