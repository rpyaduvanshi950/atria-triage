"use client";

/**
 * FLIP animation for queue reordering.
 *
 * The whole product claim is that the queue *moves*. A list that silently
 * reshuffles between frames does not show that — the nurse sees a different
 * order and has no idea who changed. Measuring each row before and after the
 * reorder, then animating the difference, is what makes an escalation
 * perceptible. (PRD QUE-003.)
 *
 * Honours prefers-reduced-motion: the movement is replaced by a brief highlight,
 * because the information must survive even when the animation does not.
 */
import { useLayoutEffect, useRef } from "react";

export function useFlip(keys: (string | number)[]) {
  const nodes = useRef(new Map<string | number, HTMLElement>());
  const previous = useRef(new Map<string | number, number>());

  const register = (key: string | number) => (el: HTMLElement | null) => {
    if (el) nodes.current.set(key, el);
    else nodes.current.delete(key);
  };

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    nodes.current.forEach((el, key) => {
      const now = el.getBoundingClientRect().top;
      const before = previous.current.get(key);
      previous.current.set(key, now);
      if (before === undefined || Math.abs(before - now) < 1) return;

      if (reduced) {
        el.animate(
          [{ backgroundColor: "rgba(69,196,178,.18)" }, { backgroundColor: "transparent" }],
          { duration: 900, easing: "ease-out" },
        );
        return;
      }
      el.animate(
        [
          { transform: `translateY(${before - now}px)` },
          { transform: "translateY(0)" },
        ],
        { duration: 650, easing: "cubic-bezier(.22,1,.36,1)" },
      );
    });
  }, [keys.join("|")]);

  return register;
}
