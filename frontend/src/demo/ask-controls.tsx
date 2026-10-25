"use client";

/**
 * Demo build only (next.config.ts aliases `@/components/ask/ask-controls` here): the same
 * controls, with the as-of picker following a picked recorded question's date.
 */
import { type ComponentProps, useEffect, useRef } from "react";

import { AsOfPicker as BaseAsOfPicker } from "../components/ask/ask-controls";
import { fromAsOfParam } from "../components/demo/demo-ask";
import { subscribePicks } from "../lib/demo/ask-store";

export { TenantSelect } from "../components/ask/ask-controls";

export function AsOfPicker(props: ComponentProps<typeof BaseAsOfPicker>) {
  const onChangeRef = useRef(props.onChange);
  useEffect(() => {
    onChangeRef.current = props.onChange;
  });
  useEffect(() => subscribePicks((pick) => onChangeRef.current(fromAsOfParam(pick.as_of))), []);
  return <BaseAsOfPicker {...props} />;
}
