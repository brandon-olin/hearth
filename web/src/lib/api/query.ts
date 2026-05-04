import createQueryClient from "openapi-react-query";
import { apiClient } from "./client";

export const $api = createQueryClient(apiClient);
