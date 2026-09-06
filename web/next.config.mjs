/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone-сборка: минимальный runtime-образ для Docker (этап 7).
  output: "standalone",
  reactStrictMode: true,
  eslint: {
    // ESLint в проект не подключён (нет зависимости/конфига), поэтому
    // сборка не должна падать из-за отсутствия линтера.
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
