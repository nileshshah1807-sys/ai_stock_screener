import type { MetadataRoute } from "next";

import { PUBLIC_PATHS, SITE_URL } from "@/lib/seo.mjs";

// Built with the deploy, so lastmod is when these pages last shipped.
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return PUBLIC_PATHS.map((path) => ({ url: path === "/" ? SITE_URL : `${SITE_URL}${path}`, lastModified }));
}
