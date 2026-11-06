import type { MetadataRoute } from "next";

import { APP_PATHS, PUBLIC_PATHS, SITE_URL } from "@/lib/seo.mjs";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: PUBLIC_PATHS, disallow: APP_PATHS },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
