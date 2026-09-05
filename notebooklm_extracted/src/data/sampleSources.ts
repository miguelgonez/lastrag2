export interface Source {
  id: string;
  title: string;
  content: string;
  type: 'text' | 'url' | 'sample';
  url?: string;
  wordCount: number;
}

export const SAMPLE_SOURCES: Source[] = [
  {
    id: "sample-voyager",
    title: "The Voyager Spacecraft Mission",
    type: "sample",
    wordCount: 395,
    content: `The Voyager spacecraft mission is one of the most successful ventures in NASA's history. Launched in 1977, the twin spacecraft, Voyager 1 and Voyager 2, were sent to explore the outer solar system and eventually venture into interstellar space. Voyager 2 was launched first on August 20, 1977, followed by Voyager 1 on September 5, 1977, on a faster trajectory.

The primary mission was to explore Jupiter and Saturn. Voyager 1 made its closest approach to Jupiter in March 1979 and reached Saturn in November 1980. Voyager 2 made its closest approaches to Jupiter in July 1979 and Saturn in August 1981. During these encounters, the probes discovered active volcanoes on Jupiter's moon Io and the complex structure of Saturn's rings.

Following its Saturn encounter, Voyager 2 went on a Grand Tour of the outer planets. It is the only spacecraft to have visited the ice giants Uranus (closest approach in January 1986) and Neptune (closest approach in August 1989). Voyager 2 discovered 10 new moons of Uranus and 6 new moons of Neptune, as well as Neptune's "Great Dark Spot."

Both spacecraft carry the Golden Record—a 12-inch gold-plated copper disk containing sounds and images selected to portray the diversity of life and culture on Earth, intended for any intelligent extraterrestrial life form that may find them. It includes greetings in 55 languages, musical selections from Bach to Chuck Berry, and natural sounds of wind, rain, and thunder.

Voyager 1 entered interstellar space on August 25, 2012, at a distance of 121 astronomical units (AU) from the Sun, becoming the first human-made object to do so. Voyager 2 followed, entering interstellar space on November 5, 2018, at 119 AU. 

Even today, after nearly 50 years in space, both spacecraft continue to send back scientific data, although many of their instruments have been turned off to conserve their fading plutonium-based nuclear power sources (Radioisotope Thermoelectric Generators). They are currently traveling through the interstellar medium, heading into the infinite dark of our galaxy.`
  },
  {
    id: "sample-coffee",
    title: "The History and Science of Coffee",
    type: "sample",
    wordCount: 412,
    content: `The story of coffee begins in the ancient forests of Ethiopia, on the Horn of Africa. According to popular legend, coffee was discovered around the 9th century by Kaldi, a young goat herder. Kaldi noticed that after eating the bright red berries of a certain wild shrub, his goats became exceptionally energetic and refused to sleep at night. He reported his findings to the abbot of a local monastery, who brewed a drink from the berries and found that it kept him alert through long hours of evening prayer.

From Ethiopia, coffee cultivated its way across the Red Sea into Yemen and the Arabian Peninsula. By the 15th century, coffee was being grown in the Yemeni district of Arabia, and by the 16th century, it was known in Persia, Egypt, Syria, and Turkey. The first coffee houses, known as 'qahveh khaneh', began appearing in cities across the Near East. They became vibrant centers of social activity, where people gathered to talk, listen to music, play chess, and discuss current events.

Coffee reached Europe in the early 17th century, where it was initially met with suspicion and referred to by some as the 'bitter invention of Satan'. However, Pope Clement VIII tasted the beverage, found it delicious, and gave it papal approval. Coffee houses quickly spread across England, France, Germany, and the Netherlands. In London, these establishments were often called 'penny universities' because for the price of a penny, one could buy a cup of coffee and engage in intellectual conversations with writers, scientists, and politicians.

From a botanical perspective, coffee belongs to the Rubiaceae family. The two most commercially significant coffee species are Coffea arabica (Arabica) and Coffea canephora (commonly known as Robusta). Arabica, which accounts for about 60% of global production, grows best at high altitudes, possesses a delicate, sweet flavor profile with high acidity, and has lower caffeine content. Robusta is hardier, grows at lower altitudes, has a more bitter, earthy flavor, and contains up to twice the caffeine of Arabica.

The roasting process is where the chemical magic happens. Raw, green coffee beans are heated to temperatures between 180°C and 250°C. This triggers the Maillard reaction—a chemical reaction between amino acids and reducing sugars—which gives roasted coffee its characteristic brown color and complex aroma, unlocking over 800 volatile compounds that define its rich flavor.`
  },
  {
    id: "sample-vite",
    title: "Introduction to Vite and Modern Frontend Tools",
    type: "sample",
    wordCount: 388,
    content: `For years, frontend developers relied on build tools like Webpack, Rollup, and Parcel to bundle their applications. While powerful, these bundlers became notoriously slow as projects grew in size. It was not uncommon for a dev server to take several minutes to start up, and Hot Module Replacement (HMR) updates could take several seconds to reflect in the browser.

In 2020, Evan You, the creator of Vue.js, introduced Vite (French for "fast", pronounced /veet/). Vite represents a paradigm shift in frontend tooling. It tackles the speed bottlenecks by leveraging two major advancements: native ES modules (ESM) in the browser, and fast compile-to-JS tools written in compiled languages.

In traditional bundling, the entire application has to be crawled, processed, and bundled into memory before the dev server can start. As a result, start time is proportional to the size of the codebase. 

Vite takes a different approach. It divides the application's code into two categories: dependency code (mostly raw JS that doesn't change often) and source code (such as JSX, TSX, or Vue files that undergo frequent editing). 

1. Dependencies are pre-bundled using esbuild. Written in Go, esbuild pre-bundles dependencies 10 to 100 times faster than traditional Node-based bundlers.
2. Source code is served over native ESM. When the browser requests a module, Vite compiles and serves that module on-the-fly. The browser does the work of linking modules together. This means the dev server starts instantly, regardless of the size of your project.

Furthermore, Vite's Hot Module Replacement is incredibly fast. Since HMR is performed over native ESM, Vite only needs to invalidate the edited module and fetch its updated version. The HMR time remains constant, no matter how many files are in the project.

For production builds, Vite employs Rollup, which is highly optimized for tree-shaking, code-splitting, and producing ultra-compact asset bundles. By combining the blazing speed of esbuild in development with the precise, production-tested bundling of Rollup, Vite provides the ultimate developer experience, making modern web development truly feel modern.`
  }
];
