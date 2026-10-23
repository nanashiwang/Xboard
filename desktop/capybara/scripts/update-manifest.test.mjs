import { test } from "node:test";
import assert from "node:assert/strict";
import {
    generateKeyPairSync,
    sign,
    randomBytes,
    createHash,
} from "node:crypto";
import { verifySignature, targets } from "./update-manifest.mjs";
const { privateKey, publicKey } = generateKeyPairSync("ed25519");
const id = randomBytes(8),
    data = Buffer.from("installer fixture");
const pub = Buffer.concat([
    Buffer.from("Ed"),
    id,
    publicKey.export({ format: "der", type: "spki" }).subarray(-32),
]);
const key = Buffer.from(
    `untrusted comment: fixture\n${pub.toString("base64")}\n`,
).toString("base64");
const signature = sign(
    null,
    createHash("blake2b512").update(data).digest(),
    privateKey,
);
const packet = Buffer.concat([Buffer.from("ED"), id, signature]);
const comment = "timestamp:123";
const globalSig = sign(
    null,
    Buffer.concat([signature, Buffer.from(comment)]),
    privateKey,
);
const encoded = Buffer.from(
    `untrusted comment: fixture\n${packet.toString("base64")}\ntrusted comment: ${comment}\n${globalSig.toString("base64")}\n`,
).toString("base64");
test("publisher verifies signed bytes and rejects modified files, comments or key ids", () => {
    verifySignature(data, encoded, key);
    assert.throws(
        () => verifySignature(Buffer.from("changed installer"), encoded, key),
        /mismatch/,
    );
    assert.throws(
        () =>
            verifySignature(
                data,
                Buffer.from(
                    Buffer.from(encoded, "base64")
                        .toString()
                        .replace("timestamp:123", "timestamp:124"),
                ).toString("base64"),
                key,
            ),
        /comment signature/,
    );
    assert.throws(() => verifySignature(data, encoded, "bad-key"), /format/);
});
test("four release targets are explicit and Linux updater uses AppImage", () => {
    assert.equal(Object.keys(targets).length, 4);
    assert.deepEqual(targets["linux-x86_64"], [
        "x86_64-unknown-linux-gnu",
        ".AppImage",
    ]);
});
