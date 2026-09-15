import {
  Pyramid,
  Castle,
  Mountain,
  TowerControl,
  Building,
  Landmark,
} from "lucide-react";
import { ExpandingCards, CardItem } from "./expanding-cards";

const architecturalWonders: CardItem[] = [
  {
    id: "pyramids-giza",
    title: "Pyramids of Giza",
    description:
      "The last surviving of the Seven Wonders of the Ancient World, these monumental tombs have stood for over 4,500 years.",
    imgSrc:
      "https://images.unsplash.com/photo-1503177119275-0aa32b3a9368?q=80&w=1000&auto=format&fit=crop",
    icon: <Pyramid size={24} />,
    linkHref: "#",
  },
  {
    id: "great-wall",
    title: "Great Wall of China",
    description:
      "A vast series of fortifications stretching thousands of miles, built to protect Chinese states and empires against raids.",
    imgSrc:
      "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?q=80&w=1000&auto=format&fit=crop",
    icon: <Castle size={24} />,
    linkHref: "#",
  },
  {
    id: "machu-picchu",
    title: "Machu Picchu",
    description:
      "An Incan citadel set high in the Andes Mountains in Peru, renowned for its sophisticated dry-stone walls that fuse huge blocks.",
    imgSrc:
      "https://images.unsplash.com/photo-1526392060635-9d6019884377?q=80&w=1000&auto=format&fit=crop",
    icon: <Mountain size={24} />,
    linkHref: "#",
  },
  {
    id: "eiffel-tower",
    title: "Eiffel Tower",
    description:
      "A global cultural icon of France and one of the most recognizable structures in the world, offering panoramic views of Paris.",
    imgSrc:
      "https://images.unsplash.com/photo-1511739001486-6bfe10ce785f?q=80&w=1000&auto=format&fit=crop",
    icon: <TowerControl size={24} />,
    linkHref: "#",
  },
  {
    id: "burj-khalifa",
    title: "Burj Khalifa",
    description:
      "The world's tallest building, a modern architectural marvel in Dubai that pierces the sky at over 828 meters.",
    imgSrc:
      "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?q=80&w=1000&auto=format&fit=crop",
    icon: <Building size={24} />,
    linkHref: "#",
  },
  {
    id: "taj-mahal",
    title: "Taj Mahal",
    description:
      "An immense mausoleum of white marble, built in Agra between 1631 and 1648 by order of the Mughal emperor Shah Jahan.",
    imgSrc:
      "https://images.unsplash.com/photo-1564507592333-c60657eea523?q=80&w=1000&auto=format&fit=crop",
    icon: <Landmark size={24} />,
    linkHref: "#",
  },
  {
    id: "colosseum",
    title: "The Colosseum",
    description:
      "The largest ancient amphitheater ever built, it remains the largest standing amphitheater in the world today.",
    imgSrc:
      "https://images.unsplash.com/photo-1552832230-c0197dd311b5?q=80&w=1000&auto=format&fit=crop",
    icon: <Landmark size={24} />,
    linkHref: "#",
  },
];

export default function ExpandingCardsDemo() {
  return (
    <div className="flex w-full flex-col items-center justify-center space-y-8 bg-background p-4 md:p-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          Architectural Wonders
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
          Explore humanity's most ambitious and breathtaking creations. Hover or
          click on a card to unveil its story.
        </p>
      </div>
      <ExpandingCards items={architecturalWonders} defaultActiveIndex={0} />
    </div>
  );
}
