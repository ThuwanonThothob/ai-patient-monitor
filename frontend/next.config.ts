/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.WARD_PORTAL === 'patient' ? '.next-patient' : '.next-staff',
  async headers() {
    return [{ source: '/sw.js', headers: [
      { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
      { key: 'Service-Worker-Allowed', value: '/' },
      { key: 'X-Content-Type-Options', value: 'nosniff' },
    ] }];
  },
  async rewrites() {
    const fallback = process.env.WARD_PORTAL === 'patient' ? 'http://127.0.0.1:8001' : 'http://127.0.0.1:8000';
    const configured = new URL(process.env.WARD_API_ORIGIN || fallback);
    if (!['http:', 'https:'].includes(configured.protocol) || configured.username || configured.password
        || configured.pathname !== '/' || configured.search || configured.hash) {
      throw new Error('WARD_API_ORIGIN must be an exact HTTP(S) backend origin');
    }
    const backend = configured.origin;
    return [{ source: '/api/:path*', destination: backend + '/api/:path*' }, { source: '/ws/:path*', destination: backend + '/ws/:path*' }];
  },
  allowedDevOrigins: [
    '100.121.42.4',
    '100.121.45.157',
    '10.32.147.225',
    '172.20.10.4',
    '10.32.87.15',
    '10.32.168.225',
    '100.121.54.27',
    '10.32.15.77',
    
    'localhost:3000'
  ],
};

export default nextConfig;
