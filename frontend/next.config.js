const createNextIntlPlugin = require('next-intl/plugin');

// next-intl 4.x: plugin path pontosan az i18n/request.ts-re mutat
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // outputFileTracingRoot: gyökér workspace warning elnyomása
  outputFileTracingRoot: require('path').join(__dirname),
};

module.exports = withNextIntl(nextConfig);
