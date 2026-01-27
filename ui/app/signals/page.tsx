import { Suspense } from "react";
import SignalsClient from "@/components/SignalsClient";

export default function SignalsPage() {
    return (
        <Suspense fallback={<div>Loading...</div>}>
            <SignalsClient />
        </Suspense>
    );
}
