"use client";

import { useLoadingMessages } from "@/lib/hooks/use-loading-messages";

export const HEARTH_LOADING_MESSAGES = [
  "Checking under the couch cushions...",
  "Rummaging through the junk drawer...",
  "Wiping down the counters...",
  "Stoking the fire...",
  "Putting the kettle on...",
  "Setting the table...",
  "Lighting the candles...",
  "Checking the pantry...",
  "Negotiating with the dishwasher...",
  "Convincing someone to do their chores...",
  "Locating the remote control...",
  "Finding a matching Tupperware lid...",
  "Pairing the socks...",
  "Organizing the spice rack...",
  "Untangling the Christmas lights...",
  "Convincing the cat to move...",
  "Waiting for the slow cooker...",
  "Briefing the houseplants...",
  "Locating the instruction manual...",
  "Brewing the coffee...",
  "Pulling dinner out of the oven...",
  "Freshening up the guest room...",
  "Drawing the curtains...",
  "Tucking everything in...",
  "Making the bed...",
  "Watering the plants...",
  "Consulting the Roomba...",
  "Attempting to fold a fitted sheet...",
  "Convincing the dog this is not walk time...",
  "Negotiating screen time...",
  "Asking the fridge why it's making that noise...",
];

/**
 * Full-screen loading state with rotating household-themed messages.
 * Drop-in replacement for simple "Loading…" text in layout gates.
 */
export function LoadingScreen() {
  const message = useLoadingMessages(HEARTH_LOADING_MESSAGES);

  return (
    <div className="min-h-full flex items-center justify-center">
      <p
        key={message}
        className="text-muted-foreground text-sm animate-in fade-in duration-500"
      >
        {message}
      </p>
    </div>
  );
}
