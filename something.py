# ============================================================================
# Generate Combined SAR Template API
# ----------------------------------------------------------------------------
# POST /api/sar/combined/generate/
#
# Clearance/approval write endpoint. Handles 11 submit_id actions covering
# the Coordinator → IPG → Solution team → publication workflow.
#
# Migrated off AssessmentMaster: every status transition is on
# RequestorTeam.status, expiration date moved to RequestorTeam.sar_expiration_date,
# SarTemplateCommentsLog replaced by LogUpdate writes.
# ============================================================================

import html
import json
from datetime import datetime

from django.conf import settings
from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import IpgResponse, LogUpdate, RequestorTeam, Role
from .services import set_comb_sar_template_data
from .utils import (
    check_file_type,
    check_user_access,
    common_email_notification,
    get_user,
    store_media,
)


# ============================================================================
# Serializer
# ============================================================================
class GenerateCombinedSarTemplateSerializer(serializers.Serializer):
    """
    No more assessmentId — sgp_id alone identifies the SAR.
    sgpId is CharField since RequestorTeam.sgp_id is a CharField PK.
    """
    sgpId = serializers.CharField(required=True, max_length=50)
    sarTemplateData = serializers.CharField(required=True)
    expirationDate = serializers.DateField(required=False, allow_null=True)
    overallRisk = serializers.CharField(required=False, allow_blank=True)
    sarComments = serializers.CharField(required=False, allow_blank=True)
    submitId = serializers.ChoiceField(
        required=True,
        choices=[
            "sar_co_approve", "sar_ipg_approve", "sar_sol_approve",
            "sar_sol_reject", "sar_co_hold", "sar_ana_approve",
            "sar_ipg_reject", "sar_co_reject", "sar_ana_reject",
            "sar_co_draft", "clearance_email_send",
        ],
    )

    def validate_expirationDate(self, value):
        submit_id = self.initial_data.get("submitId")
        if submit_id == "clearance_email_send" and not value:
            raise serializers.ValidationError(
                "Expiration date is required for clearance email send"
            )
        return value


# ============================================================================
# View
# ============================================================================
class GenerateCombinedSarTemplateAPIView(APIView):
    """
    Handles the 11 clearance-flow actions:

      sar_co_approve       → STATUS_CLEARANCE          (email Security Officer)
      sar_ipg_approve      → STATUS_CLEARANCE_SOLUTION (general email)
      sar_sol_approve      → STATUS_SAR_COMBINED_APPROVE
      sar_sol_reject       → STATUS_SAR_COMBINED_REJECT
      sar_co_hold          → STATUS_HOLD (preserves prev as pre_status)
      sar_ana_approve      → STATUS_CLEARANCE          (email Security Officer)
      sar_ipg_reject       → STATUS_SAR_COMBINED_REJECT
      sar_co_reject        → STATUS_SAR_COMBINED_REJECT
      sar_ana_reject       → STATUS_SAR_COMBINED_REJECT
      sar_co_draft         → (no status transition)
      clearance_email_send → (no status transition; uses expirationDate)
    """

    def post(self, request) -> Response:
        # ---------- auth ----------
        user, user_type, _ = get_user(request)
        if isinstance(user, Response):
            return user

        # ---------- validate ----------
        serializer = GenerateCombinedSarTemplateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "status": False,
                    "message": "There are incorrect values in the form",
                    "errors": serializer.errors,
                    "display_message": False,
                    "data": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated_data = serializer.validated_data
        sgp_id            = validated_data["sgpId"]
        sar_template_data = validated_data.get("sarTemplateData")
        overall_risk      = validated_data.get("overallRisk", "")
        submit_id         = validated_data["submitId"]
        sar_comments      = validated_data.get("sarComments", "")
        expiration_date   = validated_data.get("expirationDate")

        try:
            # ---------- resolve request ----------
            request_obj = RequestorTeam.objects.filter(sgp_id=sgp_id).first()
            if not request_obj:
                return Response(
                    {
                        "status": False,
                        "message": settings.ERRORS["invalid_request"],
                        "errors": settings.ERRORS["invalid_request"],
                        "display_message": True,
                        "data": [],
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            # ---------- access check ----------
            access_err = check_user_access(user, request_obj)
            if access_err:
                return Response(
                    {
                        "status": False,
                        "message": access_err,
                        "errors": access_err,
                        "display_message": True,
                        "data": [],
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # ---------- file type pre-check ----------
            if "secRiskAcceptDoc" in request.FILES:
                file_check = check_file_type(request.FILES["secRiskAcceptDoc"])
                if file_check:
                    return Response(
                        {
                            "status": False,
                            "message": file_check,
                            "errors": file_check,
                            "display_message": False,
                            "data": [],
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            with transaction.atomic():

                # ---------- 1. overall_risk update ----------
                if overall_risk:
                    LogUpdate.objects.create(
                        request=request_obj,
                        event=LogUpdate.RESP_EVENT,
                        old_value=request_obj.overall_risk or "-",
                        new_value=overall_risk,
                        response_for="SAR overall risk",
                        created_by=user,
                        created_date=datetime.now(),
                    )
                    request_obj.overall_risk = overall_risk.replace(" ", "")
                    request_obj.save()

                # ---------- 2. parse template payload ----------
                if isinstance(sar_template_data, str):
                    parsed = json.loads(sar_template_data.strip())
                    sar_data_dict = parsed[0] if isinstance(parsed, list) else parsed
                elif isinstance(sar_template_data, list):
                    sar_data_dict = sar_template_data[0]
                else:
                    sar_data_dict = sar_template_data

                # ---------- 3. build header_data ----------
                header_data = {
                    "input_sar_data": sar_data_dict,
                    "sar_comments":   html.escape(sar_comments) if sar_comments else "",
                    "submit_id":      submit_id,
                    "sgp_id":         request_obj.sgp_id,
                    "created_by":     user.id,
                }

                # ---------- 4. expiration_date update (now on RequestorTeam) ----------
                if expiration_date:
                    old_expiry = request_obj.sar_expiration_date
                    LogUpdate.objects.create(
                        request=request_obj,
                        event=LogUpdate.DATE_EVENT,
                        old_value=str(old_expiry) if old_expiry else "-",
                        new_value=str(expiration_date),
                        response_for="Combined SAR expiry date",
                        created_by=user,
                        created_date=datetime.now(),
                    )
                    request_obj.sar_expiration_date = expiration_date
                    request_obj.save()

                # ---------- 5. persist combined template ----------
                set_comb_sar_template_data(header_data)

                # ---------- 6. comment log ----------
                if sar_comments:
                    LogUpdate.objects.create(
                        request=request_obj,
                        event=LogUpdate.COMMENTS_EVENT,
                        old_value="-",
                        new_value=sar_comments,
                        response_for=LogUpdate.RES_FOR_CLEARANCE_COMMENT,
                        created_by=user,
                        created_date=datetime.now(),
                    )

                # ---------- 7. file upload (risk acceptance doc) ----------
                if "secRiskAcceptDoc" in request.FILES:
                    # Path now keyed on sgp_id (was assessment_id in the original)
                    location = (
                        f"{settings.RESULT_STORAGE}"
                        f"{settings.RISK_ACCEPT_STORAGE}/{sgp_id}"
                    )
                    file_name = store_media("secRiskAcceptDoc", request, location)

                    IpgResponse.objects.create(
                        request=request_obj,
                        is_high_risk="No",
                        is_medium_risk="Yes",
                        risk_acceptance_doc=file_name,
                        comments="Added by coordinator",
                        submit_id="co_risk_accept",
                        created_by=user,
                        created_date=datetime.now(),
                        is_active="1",
                    )

                    full_location = f"{settings.STORAGE_PATH}{location}/"
                    file_name_arr = file_name.split(";")
                    file_log = full_location + f"||{full_location}".join(file_name_arr)

                    LogUpdate.objects.create(
                        request=request_obj,
                        event=LogUpdate.DOC_EVENT,
                        old_value="-",
                        new_value=file_log,
                        response_for=LogUpdate.RES_FOR_CLEARANCE_COMMENT,
                        created_by=user,
                        created_date=datetime.now(),
                    )

                # ============================================================
                # 8. Dispatch on submit_id
                # ------------------------------------------------------------
                # Each branch: validate role, set new_status, optionally set
                # email_extra. The save+log+email happens once after dispatch.
                # ============================================================
                old_status      = request_obj.status
                new_status      = old_status
                email_extra     = None
                action_allowed  = False
                current_user_nm = f"{user.first_name} {user.last_name}"

                if submit_id == "sar_co_approve":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        new_status = RequestorTeam.STATUS_CLEARANCE
                        email_extra = {
                            "comments": sar_comments,
                            "request_status": RequestorTeam.STATUS_CHOICES.get(new_status),
                            "role_id": [Role.ROLE_TYPE_SECURITY_OFFICER],
                            "currentUser": current_user_nm,
                        }
                        action_allowed = True

                elif submit_id == "sar_ipg_approve":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        new_status = RequestorTeam.STATUS_CLEARANCE_SOLUTION
                        email_extra = {
                            "comments": sar_comments,
                            "request_status": RequestorTeam.STATUS_CHOICES.get(new_status),
                            "currentUser": current_user_nm,
                        }
                        action_allowed = True

                elif submit_id == "sar_sol_approve":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_RQ]:
                        new_status = RequestorTeam.STATUS_SAR_COMBINED_APPROVE
                        action_allowed = True

                elif submit_id == "sar_sol_reject":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_RQ]:
                        new_status = RequestorTeam.STATUS_SAR_COMBINED_REJECT
                        action_allowed = True

                elif submit_id == "sar_co_hold":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        request_obj.pre_status = old_status  # for un-hold restore
                        new_status = RequestorTeam.STATUS_HOLD
                        action_allowed = True

                elif submit_id == "sar_ana_approve":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_TL]:
                        new_status = RequestorTeam.STATUS_CLEARANCE
                        email_extra = {
                            "comments": sar_comments,
                            "request_status": RequestorTeam.STATUS_CHOICES.get(new_status),
                            "role_id": [Role.ROLE_TYPE_SECURITY_OFFICER],
                            "currentUser": current_user_nm,
                        }
                        action_allowed = True

                elif submit_id == "sar_ipg_reject":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        new_status = RequestorTeam.STATUS_SAR_COMBINED_REJECT
                        action_allowed = True

                elif submit_id == "sar_co_reject":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        new_status = RequestorTeam.STATUS_SAR_COMBINED_REJECT
                        action_allowed = True

                elif submit_id == "sar_ana_reject":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_TL]:
                        new_status = RequestorTeam.STATUS_SAR_COMBINED_REJECT
                        action_allowed = True

                elif submit_id == "sar_co_draft":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        # no status transition — draft action only persists template
                        action_allowed = True

                elif submit_id == "clearance_email_send":
                    if user_type in [Role.ROLE_TYPE_AU, Role.ROLE_TYPE_SECURITY_OFFICER]:
                        # no status transition — expiration_date was already saved
                        # and the actual email send presumably happens via the
                        # email_extra pathway or a separate trigger
                        action_allowed = True

                # ============================================================
                # 9. Apply transitions, log, and email
                # ============================================================
                msg = "Update Access Not Allowed"

                if action_allowed:
                    if new_status != old_status:
                        request_obj.status = new_status
                        request_obj.save()

                        LogUpdate.objects.create(
                            request=request_obj,
                            event=LogUpdate.STATUS_EVENT,
                            old_value=str(old_status),
                            new_value=str(new_status),
                            response_for=LogUpdate.RES_FOR_REQUEST,
                            created_by=user,
                            created_date=datetime.now(),
                        )

                    if email_extra:
                        common_email_notification(
                            request_obj, "analyze_request", user, email_extra
                        )

                    msg = "SAR updated successfully"

                return Response(
                    {
                        "status": True,
                        "display_message": False,
                        "message": msg,
                        "errors": [],
                        "data": [],
                    },
                    status=status.HTTP_200_OK,
                )

        except Exception as e:
            return Response(
                {
                    "status": False,
                    "message": settings.ERRORS["syntax_error_access"],
                    "errors": [str(e)],
                    "display_message": True,
                    "data": [],
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
